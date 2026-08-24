"""Stable report-link transformations shared by current and legacy findings."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def prefer_smooth_playback(href: str) -> str:
    """Keep the exact evidence tick while selecting smooth playback after it."""

    parsed = urlsplit(href)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "mode"
    ]
    query.append(("mode", "smooth"))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


__all__ = ["prefer_smooth_playback"]
