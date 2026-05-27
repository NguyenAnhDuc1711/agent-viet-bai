"""Tests for app.services.markdown_parser."""

from __future__ import annotations

from app.services.markdown_parser import parse_markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_requests(requests: list[dict], key: str) -> list[dict]:
    """Return all request dicts that contain *key* as a top-level key."""
    return [r for r in requests if key in r]


def _has_style(requests: list[dict], style_name: str) -> bool:
    """True if any updateParagraphStyle request uses *style_name*."""
    for r in _find_requests(requests, "updateParagraphStyle"):
        ps = r["updateParagraphStyle"].get("paragraphStyle", {})
        if ps.get("namedStyleType") == style_name:
            return True
    return False


# ---------------------------------------------------------------------------
# 1. Heading H1
# ---------------------------------------------------------------------------


def test_parse_heading_h1():
    plain, reqs = parse_markdown("# Title\n")
    assert plain.startswith("Title")
    assert "#" not in plain
    assert _has_style(reqs, "HEADING_1")


# ---------------------------------------------------------------------------
# 2. Heading H2
# ---------------------------------------------------------------------------


def test_parse_heading_h2():
    plain, reqs = parse_markdown("## Section\n")
    assert plain.startswith("Section")
    assert _has_style(reqs, "HEADING_2")


# ---------------------------------------------------------------------------
# 3. Bold
# ---------------------------------------------------------------------------


def test_parse_bold():
    plain, reqs = parse_markdown("This is **bold** text")
    assert plain == "This is bold text"
    bold_reqs = _find_requests(reqs, "updateTextStyle")
    assert any(
        r["updateTextStyle"]["textStyle"].get("bold") is True for r in bold_reqs
    )


# ---------------------------------------------------------------------------
# 4. Italic
# ---------------------------------------------------------------------------


def test_parse_italic():
    plain, reqs = parse_markdown("This is *italic* text")
    assert plain == "This is italic text"
    italic_reqs = _find_requests(reqs, "updateTextStyle")
    assert any(
        r["updateTextStyle"]["textStyle"].get("italic") is True
        for r in italic_reqs
    )


# ---------------------------------------------------------------------------
# 5. Bullet list
# ---------------------------------------------------------------------------


def test_parse_bullet_list():
    plain, reqs = parse_markdown("- Item 1\n- Item 2\n")
    bullet_reqs = _find_requests(reqs, "createParagraphBullets")
    assert len(bullet_reqs) >= 1  # may be merged or separate
    assert "- " not in plain


# ---------------------------------------------------------------------------
# 6. Blockquote
# ---------------------------------------------------------------------------


def test_parse_blockquote():
    plain, reqs = parse_markdown("> Quoted text\n")
    assert plain.startswith("Quoted text")
    indent_reqs = _find_requests(reqs, "updateParagraphStyle")
    assert any(
        "indentStart" in r["updateParagraphStyle"]
        .get("paragraphStyle", {})
        for r in indent_reqs
    )


# ---------------------------------------------------------------------------
# 7. Mixed formatting
# ---------------------------------------------------------------------------


def test_parse_mixed_formatting():
    md = "# Title\n\nSome **bold** and *italic* text.\n\n- bullet\n\n> quote\n"
    plain, reqs = parse_markdown(md)
    # All formatting types present
    assert _has_style(reqs, "HEADING_1")
    assert any(
        r.get("updateTextStyle", {}).get("textStyle", {}).get("bold")
        for r in reqs
    )
    assert any(
        r.get("updateTextStyle", {}).get("textStyle", {}).get("italic")
        for r in reqs
    )
    assert _find_requests(reqs, "createParagraphBullets")
    # No raw markdown symbols
    assert "**" not in plain
    assert "# " not in plain
    assert "- bullet" not in plain  # stripped prefix
    assert "> " not in plain.split("\n")[0]  # first line shouldn't start with >


# ---------------------------------------------------------------------------
# 8. Reverse order
# ---------------------------------------------------------------------------


def test_requests_reverse_order():
    md = "# Title\n\nParagraph with **bold**.\n\n## Another\n"
    _, reqs = parse_markdown(md)
    if len(reqs) < 2:
        return  # nothing to compare
    indices = []
    for r in reqs:
        for key in ("updateTextStyle", "updateParagraphStyle", "createParagraphBullets"):
            if key in r:
                indices.append(r[key]["range"]["startIndex"])
                break
    # Verify descending order
    assert indices == sorted(indices, reverse=True), (
        f"Requests not in reverse order: {indices}"
    )


# ---------------------------------------------------------------------------
# 9. No raw markdown in output
# ---------------------------------------------------------------------------


def test_no_raw_markdown_symbols():
    md = "## Heading\n\n**bold** and *italic*\n\n- list item\n\n> blockquote\n"
    plain, _ = parse_markdown(md)
    assert "##" not in plain
    assert "**" not in plain
    # Single * used for italic should be stripped
    # Check no leading "- " on list lines
    for line in plain.split("\n"):
        assert not line.startswith("- ")
        assert not line.startswith("> ")
