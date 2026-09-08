#!/usr/bin/env python3
"""Reject obvious design-system drift in public dashboard source.

This intentionally narrow, dependency-free check is not a CSS or TypeScript
parser. Palette literals belong to src/theme.css; src/styles.css is a documented
legacy exception. Diagnostics expose locations and rule names, never source text.
"""

from dataclasses import dataclass
from pathlib import Path
import re


CSS_EXCEPTIONS = {"src/theme.css", "src/styles.css"}
RAW_CSS_COLOR = re.compile(
    r"#[0-9a-f]{3,8}\b|(?<![-\w])(?:rgba?|hsla?)\s*\(",
    re.IGNORECASE,
)
CSS_URL = re.compile(r"(?<![-\w])url\s*\(", re.IGNORECASE)
STYLE_OBJECT = re.compile(r"\bstyle\s*=\s*\{\s*\{")
VISUAL_PROPERTY_NAME = r"(?:backgroundColor|borderColor|outlineColor|background|color)"
VISUAL_PROPERTY = re.compile(
    rf"(?<![\w$])(?:{VISUAL_PROPERTY_NAME}"
    rf"|(?P<quote>['\"]){VISUAL_PROPERTY_NAME}(?P=quote)"
    rf"|\[\s*(?P<computed_quote>['\"]){VISUAL_PROPERTY_NAME}(?P=computed_quote)\s*\])\s*:"
)
QUOTED_COLOR = re.compile(
    r"^\s*(?:#[0-9a-f]{3,8}\b|(?:rgba?|hsla?|var)\s*\()",
    re.IGNORECASE,
)
NAMED_COLOR = re.compile(r"[a-z][a-z0-9-]*", re.IGNORECASE)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    rule: str


def _code_mask(text: str) -> str:
    """Mask JS/TS comments and literals without changing source offsets."""
    masked = list(text)
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            else:
                masked[index] = " "
        elif block_comment:
            if char != "\n":
                masked[index] = " "
            if char == "*" and following == "/":
                masked[index + 1] = " "
                block_comment = False
                index += 1
        elif quote:
            if char != "\n":
                masked[index] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"`":
            masked[index] = " "
            quote = char
        elif char == "/" and following == "/":
            masked[index] = masked[index + 1] = " "
            line_comment = True
            index += 1
        elif char == "/" and following == "*":
            masked[index] = masked[index + 1] = " "
            block_comment = True
            index += 1
        index += 1
    return "".join(masked)


def _matching_brace(text: str, opening: int) -> int | None:
    """Return the matching JS object brace, ignoring quoted/commented braces."""
    depth = 1
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening + 1
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
        elif block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "/" and following == "/":
            line_comment = True
            index += 1
        elif char == "/" and following == "*":
            block_comment = True
            index += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _property_value(body: str, start: int) -> str:
    """Read a top-level object value through its comma or the object end."""
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    escaped = False
    index = start
    while index < len(body):
        char = body[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char in depths:
            depths[char] += 1
        elif char in closing and depths[closing[char]]:
            depths[closing[char]] -= 1
        elif char == "," and not any(depths.values()):
            return body[start:index]
        index += 1
    return body[start:]


def _without_outer_parentheses(expression: str) -> str:
    """Remove balanced parentheses that enclose the complete expression."""
    stripped = expression.strip()
    while stripped.startswith("("):
        depth = 0
        quote: str | None = None
        escaped = False
        closing = None
        for index, char in enumerate(stripped):
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in "'\"`":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing != len(stripped) - 1:
            break
        stripped = stripped[1:closing].strip()
    return stripped


def _quoted_value_spans(expression: str):
    """Yield quoted contents and their complete literal spans."""
    index = 0
    while index < len(expression):
        quote = expression[index]
        if quote not in "'\"`":
            index += 1
            continue
        literal_start = index
        content_start = index + 1
        index = content_start
        escaped = False
        while index < len(expression):
            char = expression[index]
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                yield expression[content_start:index], literal_start, index + 1
                break
            index += 1
        index += 1


def _direct_named_color_operand(expression: str, start: int, end: int) -> bool:
    """Return whether a string literal is directly joined by a branch operator."""
    while True:
        opening = start - 1
        while opening >= 0 and expression[opening].isspace():
            opening -= 1
        closing = end
        while closing < len(expression) and expression[closing].isspace():
            closing += 1
        if opening < 0 or closing >= len(expression):
            break
        if expression[opening] != "(" or expression[closing] != ")":
            break
        before_opening = opening - 1
        while before_opening >= 0 and expression[before_opening].isspace():
            before_opening -= 1
        if before_opening >= 0 and (
            expression[before_opening].isalnum()
            or expression[before_opening] in "_$])"
        ):
            break
        start = opening
        end = closing + 1

    before = expression[:start].rstrip()
    after = expression[end:].lstrip()
    return before.endswith(("?", ":", "||", "&&", "??")) or after.startswith(
        (":", "||", "&&", "??")
    )


def _has_literal_visual_value(expression: str) -> bool:
    stripped = _without_outer_parentheses(expression)
    if stripped.startswith(("'", '"', "`")):
        return True
    quoted_values = list(_quoted_value_spans(expression))
    if any(QUOTED_COLOR.match(value) for value, _, _ in quoted_values):
        return True
    return any(
        NAMED_COLOR.fullmatch(value.strip())
        and _direct_named_color_operand(expression, start, end)
        for value, start, end in quoted_values
    )


def _css_code_mask(text: str) -> str:
    """Mask CSS comments, strings, and URL functions, preserving offsets."""
    masked = list(text)
    quote: str | None = None
    escaped = False
    block_comment = False
    index = 0
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if block_comment:
            if char != "\n":
                masked[index] = " "
            if char == "*" and following == "/":
                masked[index + 1] = " "
                block_comment = False
                index += 1
        elif quote:
            if char != "\n":
                masked[index] = " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"":
            masked[index] = " "
            quote = char
        elif char == "/" and following == "*":
            masked[index] = masked[index + 1] = " "
            block_comment = True
            index += 1
        index += 1

    code = "".join(masked)
    for match in CSS_URL.finditer(code):
        depth = 1
        index = match.end()
        while index < len(code) and depth:
            if code[index] == "(":
                depth += 1
            elif code[index] == ")":
                depth -= 1
            index += 1
        for masked_index in range(match.start(), index):
            if masked[masked_index] != "\n":
                masked[masked_index] = " "
    return "".join(masked)


def _css_declaration_values(text: str):
    """Yield offset-preserving ranges that are plainly CSS declaration values."""
    code = _css_code_mask(text)
    brace_depth = 0
    value_start: int | None = None
    for index, char in enumerate(code):
        if char == "{":
            brace_depth += 1
            value_start = None
        elif char == "}":
            if value_start is not None:
                yield code, value_start, index
            value_start = None
            brace_depth = max(0, brace_depth - 1)
        elif char == ";":
            if value_start is not None:
                yield code, value_start, index
            value_start = None
        elif char == ":" and brace_depth and value_start is None:
            value_start = index + 1


def _css_findings(root: Path) -> list[Finding]:
    findings = []
    for path in sorted((root / "src").glob("**/*.css")):
        relative = path.relative_to(root).as_posix()
        if relative in CSS_EXCEPTIONS:
            continue
        text = path.read_text(encoding="utf-8")
        for code, start, end in _css_declaration_values(text):
            findings.extend(
                Finding(
                    relative,
                    text.count("\n", 0, start + match.start()) + 1,
                    "raw-color-in-modular-css",
                )
                for match in RAW_CSS_COLOR.finditer(code[start:end])
            )
    return findings


def _tsx_findings(root: Path) -> list[Finding]:
    findings = []
    for path in sorted((root / "src").glob("**/*.tsx")):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        code = _code_mask(text)
        for style in STYLE_OBJECT.finditer(code):
            opening = style.end() - 1
            ending = _matching_brace(text, opening)
            if ending is None:
                continue
            body = text[opening + 1:ending]
            body_code = _code_mask(body)
            for prop in VISUAL_PROPERTY.finditer(body):
                if body_code[prop.end() - 1] != ":":
                    continue
                value = _property_value(body, prop.end())
                if _has_literal_visual_value(value):
                    offset = opening + 1 + prop.start()
                    findings.append(Finding(
                        relative,
                        text.count("\n", 0, offset) + 1,
                        "literal-inline-visual-style",
                    ))
    return findings


def check_tree(root: Path) -> list[Finding]:
    """Return deterministic findings for a dashboard tree rooted at *root*."""
    return sorted(_css_findings(root) + _tsx_findings(root))


def main(root: Path | None = None) -> int:
    dashboard_root = root or Path(__file__).resolve().parents[1]
    findings = check_tree(dashboard_root)
    if not findings:
        print("Design system check passed.")
        return 0
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.rule}")
    print(f"Design system check failed with {len(findings)} finding(s).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
