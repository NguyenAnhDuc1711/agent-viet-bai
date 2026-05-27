"""
Markdown-to-Google-Docs-API parser.

Converts markdown text into a plain-text string and a list of Google Docs API
batch-update request objects.  Requests are returned in **reverse document
order** (highest index first) so that earlier formatting operations do not
shift the indices of later ones.

Supported syntax
----------------
- Headings: ``# H1`` through ``###### H6``
- Bold: ``**text**``
- Italic: ``*text*`` (single asterisk, not inside a bold pair)
- Bullet lists: lines starting with ``- ``
- Blockquotes: lines starting with ``> ``
"""

from __future__ import annotations

import re
from typing import Any


def parse_markdown(markdown: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse *markdown* into plain text and Google Docs API formatting requests.

    Returns
    -------
    tuple[str, list[dict]]
        ``(plain_text, requests)`` where *requests* are sorted by descending
        ``startIndex`` so they can be applied via a single ``batchUpdate``
        call without index-shift issues.
    """
    lines = markdown.split("\n")
    plain_lines: list[str] = []
    # Collected formatting metadata before we know final indices
    line_meta: list[dict[str, Any]] = []  # per output-line metadata

    for raw_line in lines:
        stripped = raw_line.rstrip("\r")

        # --- Heading ---
        heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            plain_lines.append(text)
            line_meta.append({"type": "heading", "level": level})
            continue

        # --- Bullet list ---
        if stripped.startswith("- "):
            text = stripped[2:]
            plain_lines.append(text)
            line_meta.append({"type": "bullet"})
            continue

        # --- Blockquote ---
        if stripped.startswith("> "):
            text = stripped[2:]
            plain_lines.append(text)
            line_meta.append({"type": "blockquote"})
            continue

        # --- Normal line ---
        plain_lines.append(stripped)
        line_meta.append({"type": "normal"})

    # Rejoin plain lines (preserving newlines)
    plain_text = "\n".join(plain_lines)

    # --- Collect inline formatting (bold / italic) across the full plain text ---
    inline_requests: list[dict[str, Any]] = []

    # Bold: **text**
    for m in re.finditer(r"\*\*(.+?)\*\*", plain_text):
        inline_requests.append(
            _bold_request(m.start(), m.end())
        )

    # Italic: *text* — but not inside bold markers
    for m in re.finditer(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", plain_text):
        inline_requests.append(
            _italic_request(m.start(), m.end())
        )

    # Now strip inline markers from plain_text and adjust indices
    # We need a second pass to produce the *final* plain text and remap indices.
    plain_text_final, remap = _strip_inline_markers(plain_text)

    # Remap inline request indices
    remapped_inline: list[dict[str, Any]] = []
    for req in inline_requests:
        rng = _extract_range(req)
        new_start = remap(rng["startIndex"])
        new_end = remap(rng["endIndex"])
        if new_start < new_end:
            remapped_inline.append(_set_range(req, new_start, new_end))

    # --- Collect line-level formatting using final plain text ---
    line_requests: list[dict[str, Any]] = []

    # Recompute line starts in the final plain text
    final_lines = plain_text_final.split("\n")
    pos = 1  # Google Docs body starts at index 1
    for i, line in enumerate(final_lines):
        meta = line_meta[i] if i < len(line_meta) else {"type": "normal"}
        line_end = pos + len(line)  # end of text (before newline)
        line_end_with_nl = line_end + 1  # include the newline character

        if meta["type"] == "heading":
            level = meta["level"]
            line_requests.append(
                _heading_request(pos, line_end_with_nl, level)
            )
        elif meta["type"] == "bullet":
            line_requests.append(
                _bullet_request(pos, line_end_with_nl)
            )
        elif meta["type"] == "blockquote":
            line_requests.append(
                _blockquote_request(pos, line_end_with_nl)
            )

        pos = line_end_with_nl  # move past the newline

    # Adjust inline request indices: add +1 offset for Google Docs 1-based index
    adjusted_inline: list[dict[str, Any]] = []
    for req in remapped_inline:
        rng = _extract_range(req)
        adjusted_inline.append(
            _set_range(req, rng["startIndex"] + 1, rng["endIndex"] + 1)
        )

    all_requests = line_requests + adjusted_inline

    # Sort by descending startIndex (reverse document order)
    all_requests.sort(key=_sort_key, reverse=True)

    return plain_text_final, all_requests


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_inline_markers(text: str) -> tuple[str, "callable"]:
    """Remove ``**`` and lone ``*`` markers, returning clean text and a
    function that maps old offsets to new offsets."""
    # Find all marker positions
    markers: list[tuple[int, int]] = []  # (start, length)

    # Bold markers first (** — 2 chars each)
    for m in re.finditer(r"\*\*", text):
        markers.append((m.start(), 2))

    # After removing bold markers we look for remaining single *
    # But we need to be careful: we track positions relative to original text
    # Single * that are NOT part of ** pairs
    for m in re.finditer(r"\*", text):
        pos = m.start()
        # Check this * is not part of a ** pair
        if not any(ms <= pos < ms + ml for ms, ml in markers):
            markers.append((pos, 1))

    markers.sort(key=lambda x: x[0])

    # Build offset map
    cumulative_removed = 0
    # List of (original_pos, chars_removed_before_this_pos)
    checkpoints: list[tuple[int, int]] = [(0, 0)]
    for mstart, mlen in markers:
        cumulative_removed += mlen
        checkpoints.append((mstart + mlen, cumulative_removed))

    def remap(old_pos: int) -> int:
        # Find how many characters were removed before old_pos
        removed = 0
        for cp_pos, cp_removed in checkpoints:
            if cp_pos <= old_pos:
                removed = cp_removed
            else:
                break
        return old_pos - removed

    # Build clean text
    parts: list[str] = []
    prev = 0
    for mstart, mlen in markers:
        parts.append(text[prev:mstart])
        prev = mstart + mlen
    parts.append(text[prev:])
    clean = "".join(parts)

    return clean, remap


def _extract_range(req: dict) -> dict:
    """Pull the range dict out of a request regardless of its type."""
    for key in ("updateTextStyle", "updateParagraphStyle", "createParagraphBullets"):
        if key in req:
            return req[key]["range"]
    raise KeyError(f"Unknown request type: {list(req.keys())}")


def _set_range(req: dict, start: int, end: int) -> dict:
    """Return a shallow copy of *req* with an updated range."""
    import copy
    req = copy.deepcopy(req)
    for key in ("updateTextStyle", "updateParagraphStyle", "createParagraphBullets"):
        if key in req:
            req[key]["range"]["startIndex"] = start
            req[key]["range"]["endIndex"] = end
            return req
    return req


def _sort_key(req: dict) -> int:
    """Return the startIndex for sorting."""
    for key in ("updateTextStyle", "updateParagraphStyle", "createParagraphBullets"):
        if key in req:
            return req[key]["range"]["startIndex"]
    return 0


def _heading_request(start: int, end: int, level: int) -> dict[str, Any]:
    style_name = f"HEADING_{level}"
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {"namedStyleType": style_name},
            "fields": "namedStyleType",
        }
    }


def _bold_request(start: int, end: int) -> dict[str, Any]:
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": {"bold": True},
            "fields": "bold",
        }
    }


def _italic_request(start: int, end: int) -> dict[str, Any]:
    return {
        "updateTextStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "textStyle": {"italic": True},
            "fields": "italic",
        }
    }


def _bullet_request(start: int, end: int) -> dict[str, Any]:
    return {
        "createParagraphBullets": {
            "range": {"startIndex": start, "endIndex": end},
            "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
        }
    }


def _blockquote_request(start: int, end: int) -> dict[str, Any]:
    return {
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": end},
            "paragraphStyle": {
                "indentFirstLine": {"magnitude": 36, "unit": "PT"},
                "indentStart": {"magnitude": 36, "unit": "PT"},
            },
            "fields": "indentFirstLine,indentStart",
        }
    }
