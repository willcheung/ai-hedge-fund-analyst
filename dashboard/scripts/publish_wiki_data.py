#!/usr/bin/env python3
"""Publish an already-built canonical MarketWiki JSON snapshot to Vercel Blob.

The remote manifest is authoritative. Local files are only a lock, freeze marker,
and recoverable observability/alert-deduplication cache. The Blob token is read
from the environment or an explicitly configured credential file, never argv.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from typing import Any, Callable, Iterator, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SCHEMA_VERSION = 1
PRODUCTION_PREFIX = "marketwiki"
SHADOW_PREFIX = "marketwiki/shadow"
from dashboard_config import STATE_ROOT, ENV_FILE
DEFAULT_STATE_DIR = STATE_ROOT
DEFAULT_ENV_FILE = ENV_FILE
HELPER = Path(__file__).with_name("vercel_blob_transport.mjs")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
CONTENT_TYPE_RE = re.compile(r"^application/(?:[a-z0-9.+-]*\+)?json(?:\s*;|$)", re.I)
MAX_SNAPSHOT_BYTES = 6_000_000
SNAPSHOT_SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "public-snapshot-v1.schema.json"
MANIFEST_SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "manifest-v1.schema.json"
IMMUTABLE_BODY_FIELDS = {"snapshotId", "builtAt", "publishedAt"}
FORBIDDEN_KEY_FRAGMENTS = (
    "accountnumber", "accountvalue", "accountid", "brokerid", "accesstoken", "refreshtoken",
    "authtoken", "apitoken", "bearertoken", "apikey",
    "secret", "password", "taxlot", "quantity", "sharecount", "contractcount",
    "account", "portfolio", "positionvalue", "costbasis", "realizedpnl", "unrealizedpnl", "pnl",
    "drypowder", "goalgap", "networth", "portfolioheatmap", "portfolioallocation",
)
FORBIDDEN_KEY_EXACT = {"token"}
FORBIDDEN_TEXT = (
    "/root/", "data/portfolio", "data/private", "private_local_only", "broker_access_token",
    "rhs_account_number", "current rh net", "dry powder", "goal gap",
)
PUBLIC_PRIVACY_VALUES = {None, "", "public", "public_ok"}
HEALTH_STATUSES = {"pass", "degraded", "fail"}


class PublishError(RuntimeError):
    """Classified, user-safe publisher failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ConflictError(PublishError):
    def __init__(self, message: str = "remote precondition conflict"):
        super().__init__("precondition_conflict", message, retryable=True)


class NotFoundError(PublishError):
    def __init__(self, message: str = "remote object not found"):
        super().__init__("not_found", message)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublishError("metadata_invalid", f"{field} must be a non-empty RFC3339 timestamp")
    text = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublishError("metadata_invalid", f"{field} is not RFC3339") from exc
    if parsed.tzinfo is None:
        raise PublishError("metadata_invalid", f"{field} must include a timezone")
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def validate_origin(origin: str) -> str:
    parts = urlsplit(origin)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        raise PublishError("config_invalid", "blob origin must be an HTTPS origin")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise PublishError("config_invalid", "blob origin must not contain a path, query, or fragment")
    host = parts.hostname or ""
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise PublishError("config_invalid", "blob origin must not be localhost")
    return f"https://{parts.netloc.lower()}"


def validate_prefix(prefix: str) -> str:
    if prefix not in {PRODUCTION_PREFIX, SHADOW_PREFIX}:
        raise PublishError("config_invalid", "unsupported Blob prefix")
    return prefix


def object_url(origin: str, pathname: str) -> str:
    if pathname.startswith("/") or ".." in pathname.split("/"):
        raise PublishError("path_invalid", "object path escaped configured prefix")
    return f"{origin}/{pathname}"


def validate_object_url(url: str, origin: str, prefix: str, *, exact_path: str | None = None) -> str:
    parts = urlsplit(url)
    expected = urlsplit(origin)
    if parts.scheme != "https" or parts.netloc.lower() != expected.netloc.lower() or parts.query or parts.fragment:
        raise PublishError("url_invalid", "remote URL is outside configured HTTPS origin")
    pathname = parts.path.lstrip("/")
    if exact_path is not None and pathname != exact_path:
        raise PublishError("url_invalid", "remote URL has an unexpected object path")
    if pathname != prefix and not pathname.startswith(prefix + "/"):
        raise PublishError("url_invalid", "remote URL is outside configured prefix")
    return pathname


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PublishError("json_invalid", "canonical JSON object keys must be strings")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise PublishError("json_invalid", f"NFC key collision at {normalized_key!r}")
            normalized[normalized_key] = _nfc(item)
        return normalized
    return value


def canonical_json(value: Any) -> bytes:
    try:
        return (json.dumps(_nfc(value), sort_keys=True, ensure_ascii=False, allow_nan=False,
                           separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublishError("json_invalid", f"cannot serialize JSON: {exc}") from exc


def _validate_schema(value: Any, schema_path: Path, label: str) -> None:
    if schema_path == SNAPSHOT_SCHEMA:
        # Share exact decimal meter validation and producer semantics with the
        # generator; binary float multipleOf checks reject valid tenths.
        from public_snapshot import validate_public_snapshot_schema
        try:
            validate_public_snapshot_schema(value)
        except ValueError as exc:
            raise PublishError(f"{label}_invalid", str(exc)) from exc
        return
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        from public_content import SCHEMA as content_schema
        from referencing import Registry, Resource
        registry = Registry().with_resource(content_schema["$id"], Resource.from_contents(content_schema))
        error = next(iter(Draft202012Validator(
            schema, format_checker=FormatChecker(), registry=registry,
        ).iter_errors(value)), None)
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError("schema_unavailable", f"cannot load {label} schema") from exc
    if error is not None:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        raise PublishError(f"{label}_invalid", f"{label} schema violation at {location}: {error.message}")


def _key_token(key: str) -> str:
    return "".join(character for character in key.casefold() if character.isalnum())


def _validate_public_privacy(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        privacy = value.get("privacy_class", value.get("privacyClass"))
        if privacy not in PUBLIC_PRIVACY_VALUES:
            raise PublishError("privacy_invalid", f"non-public classification at {path}")
        for key, item in value.items():
            token = _key_token(key)
            if token in FORBIDDEN_KEY_EXACT or any(fragment in token for fragment in FORBIDDEN_KEY_FRAGMENTS):
                raise PublishError("privacy_invalid", f"forbidden private key at {path}.{key}")
            _validate_public_privacy(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_public_privacy(item, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.casefold()
        marker = next((candidate for candidate in FORBIDDEN_TEXT if candidate in lowered), None)
        if marker:
            raise PublishError("privacy_invalid", f"forbidden private/path marker at {path}")


def parse_snapshot(body: bytes) -> dict[str, Any]:
    if len(body) > MAX_SNAPSHOT_BYTES:
        raise PublishError("snapshot_oversized", f"snapshot exceeds {MAX_SNAPSHOT_BYTES}-byte hard cap")
    try:
        text = body.decode("utf-8")
        value = json.loads(text, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PublishError("snapshot_invalid", "snapshot must be finite UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise PublishError("snapshot_invalid", "snapshot root must be an object")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise PublishError("schema_mismatch", f"snapshot schemaVersion must equal {SCHEMA_VERSION}")
    if body != canonical_json(value):
        raise PublishError("snapshot_noncanonical", "snapshot is noncanonical; bytes must be UTF-8 NFC, sorted compact JSON with exactly one trailing LF")
    forbidden = sorted(IMMUTABLE_BODY_FIELDS.intersection(value))
    if forbidden:
        raise PublishError("snapshot_invalid", f"immutable snapshot body contains manifest-only fields: {forbidden}")
    _validate_schema(value, SNAPSHOT_SCHEMA, "snapshot")
    _validate_public_privacy(value)
    from public_content import assert_public_suitability, PublicationError
    try:
        assert_public_suitability(value)
    except PublicationError as exc:
        raise PublishError("privacy_invalid", "snapshot must pass the shared publication boundary") from exc
    return value


def load_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError("metadata_invalid", f"cannot read {label}") from exc
    if not isinstance(value, dict):
        raise PublishError("metadata_invalid", f"{label} must contain a JSON object")
    return value


def metadata_for(snapshot: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    def pick(*names: str) -> Any:
        for source in (override, snapshot):
            for name in names:
                if source.get(name) is not None:
                    return source[name]
        return None

    built_at = parse_timestamp(pick("builtAt", "generatedAt"), "builtAt")
    source_max = parse_timestamp(pick("sourceMaxAsOf", "dataAsOf"), "sourceMaxAsOf")
    source_health = pick("sourceHealth")
    projection_status = pick("projectionStatus", "projection")
    if projection_status is None and isinstance(source_health, dict):
        projection_status = source_health.get("status")
    if not isinstance(source_health, dict):
        raise PublishError("metadata_invalid", "sourceHealth must be an object in snapshot/metadata")
    source_status = source_health.get("status")
    if source_status not in HEALTH_STATUSES:
        raise PublishError("metadata_invalid", "sourceHealth.status must be pass, degraded, or fail")
    if source_status == "fail":
        raise PublishError("source_health_failed", "sourceHealth.status fail blocks publication")
    critical = source_health.get("criticalSections")
    sections = source_health.get("sections")
    if not isinstance(critical, list) or not all(isinstance(name, str) for name in critical) or not isinstance(sections, dict):
        raise PublishError("metadata_invalid", "sourceHealth criticalSections/sections are invalid")
    for name in critical:
        section = sections.get(name)
        if not isinstance(section, dict) or section.get("status") not in HEALTH_STATUSES:
            raise PublishError("metadata_invalid", f"critical sourceHealth section {name!r} has invalid status")
        if section["status"] == "fail":
            raise PublishError("source_health_failed", f"critical sourceHealth section {name!r} failed")
    if isinstance(projection_status, dict):
        projection = projection_status
    elif isinstance(projection_status, str) and projection_status:
        projection = {"status": projection_status}
    else:
        raise PublishError("metadata_invalid", "projectionStatus must be an object or non-empty string")
    if projection.get("status") not in HEALTH_STATUSES:
        raise PublishError("metadata_invalid", "projectionStatus.status must be pass, degraded, or fail")
    if projection["status"] != "pass":
        raise PublishError("projection_failed", "projectionStatus.status must be pass for publication")
    return {
        "builtAt": built_at,
        "sourceMaxAsOf": source_max,
        "sourceHealth": source_health,
        "projectionStatus": projection,
    }


def redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    result = re.sub(r"(?i)(BLOB_READ_WRITE_TOKEN\s*[=:]\s*)\S+", r"\1[REDACTED]", result)
    result = re.sub(r"\bvercel_blob_[A-Za-z0-9_-]{12,}\b", "[REDACTED]", result)
    return result.replace("\n", " ").replace("\r", " ")[:500]


def atomic_json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)


@contextlib.contextmanager
def nonblocking_flock(path: Path) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_env_value(env_file: Path, wanted: str) -> str | None:
    value = os.environ.get(wanted)
    if value:
        return value
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == wanted:
            return value.strip().strip("'\"")
    return None


def load_token_environment(env_file: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    env = os.environ.copy()
    token = load_env_value(env_file, "BLOB_READ_WRITE_TOKEN")
    if token:
        env["BLOB_READ_WRITE_TOKEN"] = token
    return env


class NodeBlobTransport:
    def __init__(self, helper: Path = HELPER, env_file: Path = DEFAULT_ENV_FILE):
        self.helper = helper
        self.env = load_token_environment(env_file)
        self.secret = self.env.get("BLOB_READ_WRITE_TOKEN", "")

    def call(self, request: Mapping[str, Any]) -> Any:
        if not self.secret:
            raise PublishError("missing_token", "BLOB_READ_WRITE_TOKEN is not configured")
        completed = subprocess.run(
            ["node", str(self.helper)], input=json.dumps(request), text=True,
            capture_output=True, env=self.env, timeout=180, check=False,
        )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            msg = redact(completed.stderr or "Blob transport returned invalid JSON", (self.secret,))
            raise PublishError("transport_error", msg) from exc
        if completed.returncode != 0 or not response.get("ok"):
            status = response.get("status")
            message = redact(str(response.get("message") or completed.stderr or "Blob operation failed"), (self.secret,))
            code = str(response.get("code") or "transport_error")
            lowered = message.lower()
            if status in (409, 412) or "precondition" in lowered or "already exists" in lowered:
                raise ConflictError(message)
            if status == 404 or code in {"BlobNotFoundError", "blob_not_found"} or "not found" in lowered or "does not exist" in lowered:
                raise NotFoundError(message)
            raise PublishError(code, message, retryable=status in (429, 500, 502, 503, 504))
        return response["result"]

    def head(self, url: str) -> Mapping[str, Any]:
        return self.call({"op": "head", "url": url})

    def put(self, pathname: str, file: Path, *, overwrite: bool, if_match: str | None, cache_age: int) -> Mapping[str, Any]:
        return self.call({"op": "put", "pathname": pathname, "file": str(file),
                          "allowOverwrite": overwrite, "ifMatch": if_match,
                          "cacheControlMaxAge": cache_age})

    def list(self, prefix: str, cursor: str | None = None) -> Mapping[str, Any]:
        return self.call({"op": "list", "prefix": prefix, "cursor": cursor, "limit": 1000})

    def delete(self, urls: list[str]) -> None:
        if urls:
            self.call({"op": "delete", "urls": urls})


def http_get(url: str, timeout: float = 15.0) -> tuple[int, Mapping[str, str], bytes]:
    request = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read()
    except HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()
    except URLError as exc:
        raise PublishError("readback_network", "public read-back network failure", retryable=True) from exc


class Publisher:
    def __init__(self, *, origin: str, prefix: str, transport: Any,
                 fetch: Callable[[str, float], tuple[int, Mapping[str, str], bytes]] = http_get,
                 state_path: Path, freeze_path: Path, retention: int = 8,
                 propagation_attempts: int = 16, conflict_attempts: int = 4,
                 sleep: Callable[[float], None] = time.sleep):
        self.origin = validate_origin(origin)
        self.prefix = validate_prefix(prefix)
        self.transport = transport
        self.fetch = fetch
        self.state_path = state_path
        self.freeze_path = freeze_path
        self.retention = max(2, min(retention, 100))
        self.propagation_attempts = max(1, propagation_attempts)
        self.conflict_attempts = max(1, conflict_attempts)
        self.sleep = sleep
        self.manifest_path = f"{prefix}/manifest.json"
        self.manifest_url = object_url(self.origin, self.manifest_path)
        self.snapshots_prefix = f"{prefix}/snapshots/"

    def _fetch_with_bust(self, url: str, marker: str, attempt: int) -> tuple[int, Mapping[str, str], bytes]:
        separator = "&" if "?" in url else "?"
        return self.fetch(f"{url}{separator}{urlencode({'v': marker, 'attempt': attempt})}", 15.0)

    def _verify_snapshot(self, url: str, expected_hash: str, expected_size: int | None = None) -> dict[str, Any]:
        path = f"{self.snapshots_prefix}{expected_hash}.json"
        validate_object_url(url, self.origin, self.prefix, exact_path=path)
        last = "not visible"
        for attempt in range(self.propagation_attempts):
            try:
                status, headers, body = self._fetch_with_bust(url, expected_hash, attempt)
                if status != 200:
                    last = f"HTTP {status}"
                elif not CONTENT_TYPE_RE.match(headers.get("content-type", "")):
                    last = "content-type is not application/json"
                elif expected_size is not None and len(body) != expected_size:
                    last = "byte length mismatch"
                elif sha256_bytes(body) != expected_hash:
                    last = "SHA-256 mismatch"
                else:
                    snapshot = parse_snapshot(body)
                    return snapshot
            except PublishError as exc:
                last = str(exc)
            if attempt + 1 < self.propagation_attempts:
                self.sleep(min(2 ** attempt, 10))
        raise PublishError("snapshot_readback_failed", last)

    def _validate_manifest(self, value: Any) -> dict[str, Any]:
        _validate_schema(value, MANIFEST_SCHEMA, "manifest")
        if not isinstance(value, dict) or value.get("schemaVersion") != SCHEMA_VERSION:
            raise PublishError("manifest_invalid", "remote manifest schema is invalid")
        hash_value = value.get("objectSha256")
        if not isinstance(hash_value, str) or not HASH_RE.fullmatch(hash_value):
            raise PublishError("manifest_invalid", "remote manifest hash is invalid")
        expected_id = f"sha256:{hash_value}"
        if value.get("snapshotId") != expected_id or value.get("currentSnapshotId") != expected_id:
            raise PublishError("manifest_invalid", "remote manifest IDs disagree")
        expected_path = f"{self.snapshots_prefix}{hash_value}.json"
        if value.get("snapshotPath") != expected_path:
            raise PublishError("manifest_invalid", "remote manifest path is invalid")
        expected_url = object_url(self.origin, expected_path)
        if value.get("snapshotUrl") != expected_url or value.get("currentSnapshotUrl") != expected_url:
            raise PublishError("manifest_invalid", "remote manifest URL is outside configured origin/prefix")
        previous_id = value.get("previousSnapshotId")
        previous_url = value.get("previousSnapshotUrl")
        if previous_id is not None:
            if not isinstance(previous_id, str) or not previous_id.startswith("sha256:") or not HASH_RE.fullmatch(previous_id[7:]):
                raise PublishError("manifest_invalid", "previous snapshot ID is invalid")
            expected_previous = object_url(self.origin, f"{self.snapshots_prefix}{previous_id[7:]}.json")
            if previous_url != expected_previous:
                raise PublishError("manifest_invalid", "previous snapshot URL is invalid")
        elif previous_url is not None:
            raise PublishError("manifest_invalid", "previous snapshot URL exists without ID")
        if not isinstance(value.get("byteLength"), int) or value["byteLength"] < 2:
            raise PublishError("manifest_invalid", "remote manifest byteLength is invalid")
        if not isinstance(value.get("sourceHealth"), dict):
            raise PublishError("manifest_invalid", "remote manifest sourceHealth is invalid")
        if not isinstance(value.get("projectionStatus"), dict) or not isinstance(value["projectionStatus"].get("status"), str):
            raise PublishError("manifest_invalid", "remote manifest projectionStatus is invalid")
        parse_timestamp(value.get("builtAt"), "manifest builtAt")
        parse_timestamp(value.get("publishedAt"), "manifest publishedAt")
        parse_timestamp(value.get("sourceMaxAsOf"), "manifest sourceMaxAsOf")
        history = value.get("history", [])
        if not isinstance(history, list) or len(history) > 100:
            raise PublishError("manifest_invalid", "remote manifest history is invalid")
        for item in history:
            if not isinstance(item, dict):
                raise PublishError("manifest_invalid", "remote manifest history entry is invalid")
            item_hash = item.get("objectSha256")
            if not isinstance(item_hash, str) or not HASH_RE.fullmatch(item_hash):
                raise PublishError("manifest_invalid", "remote history hash is invalid")
            if item.get("snapshotId") != f"sha256:{item_hash}":
                raise PublishError("manifest_invalid", "remote history ID is invalid")
            item_path = f"{self.snapshots_prefix}{item_hash}.json"
            if item.get("snapshotPath") != item_path or item.get("snapshotUrl") != object_url(self.origin, item_path):
                raise PublishError("manifest_invalid", "remote history URL/path is invalid")
        if previous_id is not None and (not history or history[0].get("snapshotId") != previous_id):
            raise PublishError("manifest_invalid", "previous snapshot is not the first retained history entry")
        return value

    def read_remote_manifest(self) -> tuple[dict[str, Any] | None, str | None]:
        try:
            metadata = self.transport.head(self.manifest_url)
        except NotFoundError:
            return None, None
        etag = metadata.get("etag")
        if not isinstance(etag, str) or not etag:
            raise PublishError("manifest_invalid", "remote manifest ETag is missing")
        last = "manifest not visible"
        for attempt in range(self.propagation_attempts):
            status, headers, body = self._fetch_with_bust(self.manifest_url, etag, attempt)
            if status == 404:
                last = "manifest HEAD exists but public GET is 404"
            elif status != 200:
                last = f"manifest public GET returned HTTP {status}"
            elif not CONTENT_TYPE_RE.match(headers.get("content-type", "")):
                last = "manifest content-type is not application/json"
            else:
                response_etag = headers.get("etag")
                if response_etag and response_etag.strip('"') != etag.strip('"'):
                    last = "manifest public ETag is stale"
                else:
                    try:
                        return self._validate_manifest(json.loads(body)), etag
                    except (json.JSONDecodeError, PublishError) as exc:
                        last = str(exc)
            if attempt + 1 < self.propagation_attempts:
                self.sleep(min(2 ** attempt, 10))
        raise PublishError("manifest_readback_failed", last)

    def _entry(self, hash_value: str, byte_length: int, metadata: Mapping[str, Any], published_at: str) -> dict[str, Any]:
        return {
            "snapshotId": f"sha256:{hash_value}",
            "snapshotPath": f"{self.snapshots_prefix}{hash_value}.json",
            "snapshotUrl": object_url(self.origin, f"{self.snapshots_prefix}{hash_value}.json"),
            "objectSha256": hash_value,
            "byteLength": byte_length,
            "builtAt": metadata["builtAt"],
            "publishedAt": published_at,
            "sourceMaxAsOf": metadata["sourceMaxAsOf"],
            "sourceHealth": metadata["sourceHealth"],
            "projectionStatus": metadata["projectionStatus"],
        }

    @staticmethod
    def _manifest_entry(manifest: Mapping[str, Any]) -> dict[str, Any]:
        keys = ("snapshotId", "snapshotPath", "snapshotUrl", "objectSha256", "byteLength",
                "builtAt", "publishedAt", "sourceMaxAsOf", "sourceHealth", "projectionStatus")
        return {key: manifest[key] for key in keys if key in manifest}

    def _build_manifest(self, entry: Mapping[str, Any], remote: Mapping[str, Any] | None) -> dict[str, Any]:
        prior_entries: list[Mapping[str, Any]] = []
        if remote:
            prior_entries.append(self._manifest_entry(remote))
            if isinstance(remote.get("history"), list):
                prior_entries.extend(item for item in remote["history"] if isinstance(item, dict))
        history: list[dict[str, Any]] = []
        seen = {entry["snapshotId"]}
        for item in prior_entries:
            sid = item.get("snapshotId")
            if isinstance(sid, str) and sid not in seen:
                seen.add(sid)
                history.append(dict(item))
            if len(history) >= self.retention - 1:
                break
        previous = history[0] if history else None
        manifest = {"schemaVersion": SCHEMA_VERSION, **entry,
                    "currentSnapshotId": entry["snapshotId"], "currentSnapshotUrl": entry["snapshotUrl"],
                    "previousSnapshotId": previous.get("snapshotId") if previous else None,
                    "previousSnapshotUrl": previous.get("snapshotUrl") if previous else None,
                    "history": history}
        return manifest

    def _put_bytes(self, pathname: str, body: bytes, *, overwrite: bool, if_match: str | None, cache_age: int) -> Mapping[str, Any]:
        fd, name = tempfile.mkstemp(prefix="marketwiki-publish-", suffix=".json")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            return self.transport.put(pathname, Path(name), overwrite=overwrite, if_match=if_match, cache_age=cache_age)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name)

    def _ensure_snapshot(self, snapshot_path: Path, body: bytes, hash_value: str) -> str:
        pathname = f"{self.snapshots_prefix}{hash_value}.json"
        url = object_url(self.origin, pathname)
        try:
            result = self.transport.put(pathname, snapshot_path, overwrite=False, if_match=None, cache_age=31536000)
            returned_url = result.get("url")
            validate_object_url(returned_url, self.origin, self.prefix, exact_path=pathname)
        except ConflictError:
            pass
        self._verify_snapshot(url, hash_value, len(body))
        return url

    def _verify_manifest_public(self, expected: Mapping[str, Any]) -> None:
        expected_hash = expected["objectSha256"]
        last = "manifest not propagated"
        for attempt in range(self.propagation_attempts):
            status, headers, body = self._fetch_with_bust(self.manifest_url, expected_hash, attempt)
            if status == 200 and CONTENT_TYPE_RE.match(headers.get("content-type", "")):
                try:
                    actual = self._validate_manifest(json.loads(body))
                    if actual.get("snapshotId") == expected.get("snapshotId"):
                        self._verify_snapshot(actual["snapshotUrl"], expected_hash, expected["byteLength"])
                        return
                    last = "public manifest still points to old snapshot"
                except (json.JSONDecodeError, PublishError) as exc:
                    last = str(exc)
            else:
                last = f"manifest read-back HTTP/content-type failure ({status})"
            if attempt + 1 < self.propagation_attempts:
                self.sleep(min(2 ** attempt, 10))
        raise PublishError("manifest_readback_failed", last)

    def publish(self, snapshot_path: Path, override: Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        if self.freeze_path.exists():
            raise PublishError("publisher_frozen", f"publisher frozen by {self.freeze_path}")
        try:
            body = snapshot_path.read_bytes()
        except OSError as exc:
            raise PublishError("snapshot_unreadable", "cannot read snapshot file") from exc
        snapshot = parse_snapshot(body)
        metadata = metadata_for(snapshot, override)
        hash_value = sha256_bytes(body)
        snapshot_url = object_url(self.origin, f"{self.snapshots_prefix}{hash_value}.json")
        remote, _ = self.read_remote_manifest()
        plan = {"action": "no_change" if remote and remote["objectSha256"] == hash_value else "publish",
                "snapshotId": f"sha256:{hash_value}", "snapshotUrl": snapshot_url, "byteLength": len(body),
                "remoteSnapshotId": remote.get("snapshotId") if remote else None}
        if not remote or remote["objectSha256"] != hash_value:
            # Validate the exact local manifest shape before the immutable snapshot
            # upload. Conflict retries validate each subsequently reconciled build too.
            preflight_entry = self._entry(hash_value, len(body), metadata, utc_now())
            self._validate_manifest(self._build_manifest(preflight_entry, remote))
        if dry_run:
            return plan
        if remote and remote["objectSha256"] == hash_value:
            self._verify_snapshot(snapshot_url, hash_value, len(body))
            self._apply_retention(remote)
            self._record_success(remote, "no_change")
            return plan
        self._ensure_snapshot(snapshot_path, body, hash_value)
        last_conflict: PublishError | None = None
        for attempt in range(self.conflict_attempts):
            remote, etag = self.read_remote_manifest()
            if remote and remote["objectSha256"] == hash_value:
                self._verify_snapshot(snapshot_url, hash_value, len(body))
                self._apply_retention(remote)
                self._record_success(remote, "converged")
                return {**plan, "action": "converged"}
            published_at = utc_now()
            entry = self._entry(hash_value, len(body), metadata, published_at)
            manifest = self._build_manifest(entry, remote)
            self._validate_manifest(manifest)
            manifest_body = canonical_json(manifest)
            try:
                result = self._put_bytes(self.manifest_path, manifest_body, overwrite=remote is not None,
                                         if_match=etag, cache_age=60)
                validate_object_url(result.get("url"), self.origin, self.prefix, exact_path=self.manifest_path)
                self._verify_manifest_public(manifest)
                self._apply_retention(manifest)
                self._record_success(manifest, "published")
                return {**plan, "action": "published", "previousSnapshotId": manifest["previousSnapshotId"]}
            except ConflictError as exc:
                last_conflict = exc
                if attempt + 1 < self.conflict_attempts:
                    self.sleep(min(2 ** attempt, 5))
        raise last_conflict or ConflictError()

    def _all_snapshot_blobs(self) -> list[dict[str, Any]]:
        blobs: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(100):
            page = self.transport.list(self.snapshots_prefix, cursor)
            page_blobs = page.get("blobs", [])
            if not isinstance(page_blobs, list):
                raise PublishError("transport_error", "Blob list response is invalid")
            for blob in page_blobs:
                if not isinstance(blob, dict):
                    continue
                pathname = blob.get("pathname")
                url = blob.get("url")
                if isinstance(pathname, str) and isinstance(url, str):
                    validate_object_url(url, self.origin, self.prefix, exact_path=pathname)
                    if pathname.startswith(self.snapshots_prefix):
                        blobs.append(blob)
            cursor = page.get("cursor")
            if not cursor:
                break
        else:
            raise PublishError("retention_failed", "Blob listing exceeded pagination bound")
        return blobs

    def _apply_retention(self, manifest: Mapping[str, Any]) -> list[str]:
        protected = {manifest["snapshotUrl"]}
        if manifest.get("previousSnapshotUrl"):
            protected.add(manifest["previousSnapshotUrl"])
        blobs = sorted(self._all_snapshot_blobs(), key=lambda item: str(item.get("uploadedAt", "")), reverse=True)
        keep = set(protected)
        for blob in blobs:
            if len(keep) >= self.retention:
                break
            keep.add(blob["url"])
        delete_urls = [blob["url"] for blob in blobs if blob["url"] not in keep]
        self.transport.delete(delete_urls)
        return delete_urls

    @staticmethod
    def _find_retained_entry(manifest: Mapping[str, Any], snapshot_id: str) -> dict[str, Any] | None:
        current = Publisher._manifest_entry(manifest)
        if current.get("snapshotId") == snapshot_id:
            return current
        history = manifest.get("history", [])
        if isinstance(history, list):
            for item in history:
                if isinstance(item, dict) and item.get("snapshotId") == snapshot_id:
                    return dict(item)
        return None

    def rollback(self, snapshot_id: str) -> dict[str, Any]:
        if not self.freeze_path.exists():
            raise PublishError("freeze_required", "rollback requires publisher freeze")
        hash_value = snapshot_id.removeprefix("sha256:")
        if not HASH_RE.fullmatch(hash_value):
            raise PublishError("rollback_invalid", "rollback snapshot ID must be sha256:<64 lowercase hex>")
        target_id = f"sha256:{hash_value}"
        target_url = object_url(self.origin, f"{self.snapshots_prefix}{hash_value}.json")
        for attempt in range(self.conflict_attempts):
            remote, etag = self.read_remote_manifest()
            if remote is None:
                raise PublishError("rollback_invalid", "cannot rollback without an existing manifest")
            if remote["objectSha256"] == hash_value:
                self._record_success(remote, "rollback_no_change")
                return remote
            retained = self._find_retained_entry(remote, target_id)
            if retained is None:
                raise PublishError("rollback_invalid", "rollback target is not in remote retained history")
            head_size = self.transport.head(target_url).get("size")
            expected_size = retained.get("byteLength")
            if not isinstance(head_size, int) or not isinstance(expected_size, int) or head_size != expected_size:
                raise PublishError("rollback_invalid", "retained snapshot HEAD size does not match manifest history")
            self._verify_snapshot(target_url, hash_value, expected_size)
            target_metadata = {
                "builtAt": retained.get("builtAt"),
                "sourceMaxAsOf": retained.get("sourceMaxAsOf"),
                "sourceHealth": retained.get("sourceHealth"),
                "projectionStatus": retained.get("projectionStatus"),
            }
            # Revalidate retained manifest metadata before republishing it.
            target_metadata = metadata_for({}, target_metadata)
            entry = self._entry(hash_value, expected_size, target_metadata, utc_now())
            manifest = self._build_manifest(entry, remote)
            self._validate_manifest(manifest)
            try:
                result = self._put_bytes(self.manifest_path, canonical_json(manifest), overwrite=True,
                                         if_match=etag, cache_age=60)
                validate_object_url(result.get("url"), self.origin, self.prefix, exact_path=self.manifest_path)
                self._verify_manifest_public(manifest)
                self._record_success(manifest, "rolled_back")
                return manifest
            except ConflictError:
                if attempt + 1 >= self.conflict_attempts:
                    raise
                self.sleep(min(2 ** attempt, 5))
        raise ConflictError()

    def emergency_delete(self, snapshot_id: str, *, allow_active: bool = False) -> list[str]:
        if not self.freeze_path.exists():
            raise PublishError("freeze_required", "emergency deletion requires publisher freeze")
        hash_value = snapshot_id.removeprefix("sha256:")
        if not HASH_RE.fullmatch(hash_value):
            raise PublishError("delete_invalid", "snapshot ID must be sha256:<64 lowercase hex>")
        remote, _ = self.read_remote_manifest()
        sid = f"sha256:{hash_value}"
        if remote and not allow_active and sid in {remote.get("snapshotId"), remote.get("previousSnapshotId")}:
            raise PublishError("delete_active", "refusing to delete current/previous snapshot without --allow-active")
        expected_path = f"{self.snapshots_prefix}{hash_value}.json"
        matches = []
        for blob in self._all_snapshot_blobs():
            if blob.get("pathname") == expected_path:
                matches.append(blob["url"])
        if not matches:
            raise NotFoundError("retained snapshot not found")
        self.transport.delete(matches)
        return matches

    def _record_success(self, manifest: Mapping[str, Any], action: str) -> None:
        state = {
            "schemaVersion": 1, "recoveredFromRemote": True, "lastAction": action,
            "lastAttemptAt": utc_now(), "lastSuccessAt": utc_now(),
            "lastSuccessfulSnapshotId": manifest.get("snapshotId"),
            "previousSnapshotId": manifest.get("previousSnapshotId"),
            "lastSourceMaxAsOf": manifest.get("sourceMaxAsOf"),
            "lastBuiltAt": manifest.get("builtAt"), "lastPublishedAt": manifest.get("publishedAt"),
            "lastByteLength": manifest.get("byteLength"), "consecutiveFailures": 0,
            "lastError": None, "alertDue": False,
        }
        atomic_json_write(self.state_path, state)

    def record_failure(self, error: PublishError, *, cooldown_seconds: int = 3600) -> bool:
        prior: dict[str, Any] = {}
        with contextlib.suppress(OSError, json.JSONDecodeError):
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                prior = loaded
        message = redact(str(error), (getattr(self.transport, "secret", ""),))
        signature = hashlib.sha256(f"{error.code}:{message}".encode()).hexdigest()
        now = dt.datetime.now(dt.timezone.utc)
        last_alert = prior.get("lastAlertAt")
        within_cooldown = False
        if prior.get("lastErrorSignature") == signature and isinstance(last_alert, str):
            with contextlib.suppress(ValueError):
                within_cooldown = (now - dt.datetime.fromisoformat(last_alert.replace("Z", "+00:00"))).total_seconds() < cooldown_seconds
        alert_due = not within_cooldown
        state = dict(prior)
        state.update({"schemaVersion": 1, "lastAttemptAt": utc_now(),
                      "consecutiveFailures": int(prior.get("consecutiveFailures", 0)) + 1,
                      "lastError": {"class": error.code, "message": message},
                      "lastErrorSignature": signature, "alertDue": alert_due})
        if alert_due:
            state["lastAlertAt"] = utc_now()
        atomic_json_write(self.state_path, state)
        return alert_due


def mode_paths(args: argparse.Namespace) -> tuple[str, Path, Path, Path]:
    suffix = "_shadow" if args.shadow else ""
    prefix = SHADOW_PREFIX if args.shadow else PRODUCTION_PREFIX
    state_dir = Path(args.state_dir)
    return prefix, state_dir / f"market_dashboard_data_publish_state{suffix}.json", state_dir / f"market_dashboard_data_publish{suffix}.freeze", state_dir / f"market_dashboard_data_publish{suffix}.lock"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish immutable MarketWiki snapshots independently of the dashboard app.")
    parser.add_argument("--blob-origin", default=os.environ.get("MARKETWIKI_BLOB_ORIGIN"), help="Fixed HTTPS Vercel Blob origin (or MARKETWIKI_BLOB_ORIGIN).")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR), help="Local recoverable state/lock/freeze directory.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Protected env file used only when token is absent from environment.")
    parser.add_argument("--shadow", action="store_true", help="Use isolated marketwiki/shadow objects and state; never mutate production manifest.")
    parser.add_argument("--retention", type=int, default=8, help="Total recent snapshots to retain (minimum 2, default 8).")
    parser.add_argument("--propagation-attempts", type=int, default=10, help="Bounded public read-back attempts (default spans at least 60 seconds).")
    parser.add_argument("--conflict-attempts", type=int, default=4, help="Bounded manifest precondition retries.")
    sub = parser.add_subparsers(dest="command", required=True)
    publish = sub.add_parser("publish", help="Publish an already-built canonical snapshot file.")
    publish.add_argument("snapshot", type=Path)
    publish.add_argument("--metadata", type=Path, help="JSON metadata override (never credentials).")
    publish.add_argument("--built-at")
    publish.add_argument("--source-max-as-of")
    publish.add_argument("--source-health-json")
    publish.add_argument("--projection-status")
    publish.add_argument("--dry-run", action="store_true", help="Read/validate/plan only; perform no Blob or state writes.")
    freeze = sub.add_parser("freeze", help="Atomically freeze forward publishing before rollback/incident response.")
    freeze.add_argument("--reason", default="manual freeze")
    sub.add_parser("unfreeze", help="Remove the freeze marker after forward publishing is safe.")
    rollback = sub.add_parser("rollback", help="Conditionally point manifest at a verified retained snapshot; requires freeze.")
    rollback.add_argument("snapshot_id")
    delete = sub.add_parser("emergency-delete", help="Delete a retained immutable snapshot during an incident; requires freeze.")
    delete.add_argument("snapshot_id")
    delete.add_argument("--confirm-delete", action="store_true", required=True)
    delete.add_argument("--allow-active", action="store_true", help="Allow deleting current/previous pointer target (manifest will be broken).")
    sub.add_parser("status", help="Recover and print non-sensitive status from remote manifest plus local cache.")
    return parser


def publisher_from_args(args: argparse.Namespace, prefix: str, state: Path, freeze: Path) -> Publisher:
    env_file = Path(args.env_file)
    origin = args.blob_origin or load_env_value(env_file, "MARKETWIKI_BLOB_ORIGIN")
    if not origin:
        raise PublishError("config_invalid", "--blob-origin or MARKETWIKI_BLOB_ORIGIN is required")
    return Publisher(origin=origin, prefix=prefix,
                     transport=NodeBlobTransport(env_file=env_file),
                     state_path=state, freeze_path=freeze, retention=args.retention,
                     propagation_attempts=args.propagation_attempts, conflict_attempts=args.conflict_attempts)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    prefix, state_path, freeze_path, lock_path = mode_paths(args)
    if args.command == "freeze":
        with nonblocking_flock(lock_path) as acquired:
            if not acquired:
                return 0
            atomic_json_write(freeze_path, {"schemaVersion": 1, "frozenAt": utc_now(), "reason": args.reason[:200]})
        return 0
    if args.command == "unfreeze":
        with nonblocking_flock(lock_path) as acquired:
            if not acquired:
                return 0
            freeze_path.unlink(missing_ok=True)
        return 0
    try:
        publisher = publisher_from_args(args, prefix, state_path, freeze_path)
        with nonblocking_flock(lock_path) as acquired:
            if not acquired:
                return 0
            if args.command == "publish":
                override = load_json_file(args.metadata, "metadata") if args.metadata else {}
                if args.built_at:
                    override["builtAt"] = args.built_at
                elif "builtAt" not in override:
                    override["builtAt"] = dt.datetime.fromtimestamp(
                        args.snapshot.stat().st_mtime, dt.timezone.utc
                    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                if args.source_max_as_of:
                    override["sourceMaxAsOf"] = args.source_max_as_of
                if args.source_health_json:
                    try:
                        override["sourceHealth"] = json.loads(args.source_health_json)
                    except json.JSONDecodeError as exc:
                        raise PublishError("metadata_invalid", "--source-health-json is invalid JSON") from exc
                if args.projection_status:
                    override["projectionStatus"] = args.projection_status
                result = publisher.publish(args.snapshot, override, dry_run=args.dry_run)
                if args.dry_run:
                    print(json.dumps(result, sort_keys=True))
            elif args.command == "rollback":
                publisher.rollback(args.snapshot_id)
            elif args.command == "emergency-delete":
                publisher.emergency_delete(args.snapshot_id, allow_active=args.allow_active)
            elif args.command == "status":
                manifest, etag = publisher.read_remote_manifest()
                local = None
                with contextlib.suppress(OSError, json.JSONDecodeError):
                    local = json.loads(state_path.read_text(encoding="utf-8"))
                print(json.dumps({"remoteManifest": manifest, "remoteEtag": etag, "localCache": local}, sort_keys=True))
        return 0
    except PublishError as exc:
        alert_due = False
        is_dry_run = args.command == "publish" and getattr(args, "dry_run", False)
        if not is_dry_run:
            with contextlib.suppress(Exception):
                alert_due = publisher.record_failure(exc)  # type: ignore[possibly-undefined]
        print(f"publisher_error class={exc.code} alert={'true' if alert_due else 'false'} message={redact(str(exc))}", file=sys.stderr)
        return 2
    except Exception as exc:  # defensive boundary: never leak transport internals/tokens
        secret = getattr(getattr(locals().get("publisher"), "transport", None), "secret", "")
        detail = redact(f"{type(exc).__name__}: {exc}", (secret,))
        safe = PublishError("unexpected_error", detail)
        is_dry_run = args.command == "publish" and getattr(args, "dry_run", False)
        if not is_dry_run:
            with contextlib.suppress(Exception):
                publisher.record_failure(safe)  # type: ignore[possibly-undefined]
        print(f"publisher_error class=unexpected_error alert=true message={detail}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
