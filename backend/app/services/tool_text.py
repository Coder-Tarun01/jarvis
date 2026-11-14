"""Recover tool calls that a model wrote as *text* instead of as structured calls.

Some distilled/quantised models (observed with ``baidu/ernie-5.5-flash-preview:free``
through OpenRouter) were trained on transcripts where invocations appear inline, so
they answer with::

    [used tools] open_desktop_app(app="whatsapp")
    WhatsApp's open.

The provider's ``tool_calls`` payload stays empty, so nothing runs and the user is
told an action happened that never did. This module recognises that shape — but only
for tools that were actually offered in the request — and converts it into real
calls, returning the leftover prose for the visible answer.

Being conservative matters more than being clever: a call is only recovered when a
line *starts* with a known tool name followed by parentheses, so ordinary prose
("I would use open_desktop_app for that") is never executed.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

#: prefixes models put in front of an inline call
_MARKERS = (
    "[used tools]",
    "[used tool]",
    "[tool]",
    "[tool call]",
    "[tool_call]",
    "used tools:",
    "used tool:",
)
_BULLETS = "*->•–—•"
_NUMBER_LITERAL = re.compile(r"^-?\d+(?:\.\d+)?$")


def _strip_prefix(line: str) -> str:
    """Drop bullets, quotes and an inline-call marker from the start of a line."""
    text = line.lstrip()
    changed = True
    while changed:
        changed = False
        for marker in _MARKERS:
            if text.lower().startswith(marker):
                text = text[len(marker):].lstrip()
                changed = True
        while text[:1] and text[0] in _BULLETS:
            text = text[1:].lstrip()
            changed = True
        if text[:1] in ("`",):
            text = text[1:].lstrip()
            changed = True
    return text


def _balanced_parens(text: str, start: int) -> tuple[str, int] | None:
    """Return (inside, index_after_close) for the '(' at ``start``, quotes respected."""
    if start >= len(text) or text[start] != "(":
        return None
    depth = 0
    quote = ""
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if char == quote and text[index - 1] != "\\":
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
    return None


def _coerce(value: str):
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "none"):
        return None
    if _NUMBER_LITERAL.match(text):
        return float(text) if "." in text else int(text)
    return text


def _parse_arguments(raw: str) -> dict:
    """``{"a": 1}`` or ``app="whatsapp", force=True`` -> dict."""
    text = raw.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    if parsed is not None:
        return {"value": parsed}

    arguments: dict = {}
    pieces = re.split(r",\s*(?=[A-Za-z_][A-Za-z0-9_]*\s*=)", text)
    for piece in pieces:
        key, separator, value = piece.partition("=")
        if not separator:
            continue
        key = key.strip().strip("\"'")
        if key and re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            arguments[key] = _coerce(value)
    return arguments


def recover_tool_calls(
    text: str, allowed: Iterable[str]
) -> tuple[list[tuple[str, dict]], str]:
    """Find inline ``tool(arg=value)`` calls in ``text``.

    Returns ``(calls, cleaned_text)`` where ``calls`` is a list of
    ``(tool_name, arguments)`` pairs. ``cleaned_text`` has the call lines removed, so
    the UI does not show the model's invented call syntax.
    """
    names = sorted({name for name in allowed if name}, key=len, reverse=True)
    if not text or not names:
        return [], text

    alternation = "|".join(re.escape(name) for name in names)
    pattern = re.compile(
        rf"(?m)^[ \t>*\-{_BULLETS}]*"
        rf"(?:\[used tools?\]|\[tool(?:_call)? ?\]|used tools?:)?[ \t]*"
        rf"(?P<name>{alternation})[ \t]*\(",
        re.IGNORECASE,
    )

    calls: list[tuple[str, dict]] = []
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(text):
        paren = text.find("(", match.end() - 1)
        parsed = _balanced_parens(text, paren)
        if parsed is None:
            continue  # unbalanced: not a call, leave the text alone
        inside, end = parsed
        name = match.group("name")
        # keep the tool's own spelling, not the model's capitalisation
        canonical = next((known for known in names if known.lower() == name.lower()), name)
        calls.append((canonical, _parse_arguments(inside)))
        start = match.start()
        spans.append((start, end))

    if not calls:
        return [], text

    cleaned_parts: list[str] = []
    cursor = 0
    for start, end in spans:
        cleaned_parts.append(text[cursor:start])
        cursor = end
        # swallow the rest of that line's trailing whitespace
        while cursor < len(text) and text[cursor] in " \t\r":
            cursor += 1
        if cursor < len(text) and text[cursor] == "\n":
            cursor += 1
    cleaned_parts.append(text[cursor:])

    cleaned = "".join(cleaned_parts)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return calls, cleaned
