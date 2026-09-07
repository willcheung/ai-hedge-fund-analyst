#!/usr/bin/env bash
# Trusted entry: env -i PATH="$PATH" STAGING_ROOT=/disposable/checkout bash offline.sh COMMAND...
set -euo pipefail
if [ "$#" -eq 0 ] || [ -z "${STAGING_ROOT:-}" ]; then
  printf 'Set STAGING_ROOT to a disposable tree and supply a command.\n' >&2
  exit 2
fi
root=$(realpath -e "$STAGING_ROOT")
case "$root" in
  /|/root|/root/*|/tmp|/home|/usr|/opt|/var|/etc|/run)
    printf 'Refusing a live/broad staging mount.\n' >&2; exit 2 ;;
esac
cwd=$(pwd -P)
case "$cwd/" in "$root/"*) ;; *) printf 'Workdir must be inside STAGING_ROOT.\n' >&2; exit 2 ;; esac
# Keep only the reviewed system/toolchain trees, never host /proc, /run or /tmp.
mounts=(--ro-bind /usr /usr)
for path in /bin /sbin /lib /lib64 /etc/ld.so.cache /etc/fonts /opt/hostedtoolcache; do
  if [ -e "$path" ]; then mounts+=(--ro-bind "$path" "$path"); fi
done
# No shell starts inside the sandbox before the environment is cleared.
exec env -i PATH=/usr/bin:/bin bwrap --unshare-all --die-with-parent --new-session \
  --cap-drop ALL "${mounts[@]}" --proc /proc --dev /dev --tmpfs /tmp \
  --dir /run --dir /root --dir /tmp/home --dir /tmp/hermes --dir /tmp/cache \
  --bind "$root" "$root" --chdir "$cwd" --clearenv \
  --setenv PATH "$PATH" --setenv HOME /tmp/home --setenv HERMES_HOME /tmp/hermes \
  --setenv XDG_CACHE_HOME /tmp/cache --setenv TMPDIR /tmp --setenv PYTHONDONTWRITEBYTECODE 1 \
  --setenv TZ UTC --setenv LANG C.UTF-8 --setenv CI 1 --setenv NO_COLOR 1 "$@"
