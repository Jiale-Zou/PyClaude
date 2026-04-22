from __future__ import annotations


def summarize(text: str, max_chars: int = 1000) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 10] + "\n...[snip]"
