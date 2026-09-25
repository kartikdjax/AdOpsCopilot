"""Recursive, structure-aware document chunking. See Week 2 Day 1 for the full walkthrough."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str
    chunk_index: int


def _split_recursive(text: str, max_size: int, separators: list[str]) -> list[str]:
    if len(text) <= max_size or not separators:
        return [text]
    sep, remaining = separators[0], separators[1:]
    parts = text.split(sep)
    result: list[str] = []
    buffer = ""
    for part in parts:
        candidate = (buffer + sep + part) if buffer else part
        if len(candidate) <= max_size:
            buffer = candidate
        else:
            if buffer:
                result.append(buffer)
            if len(part) > max_size:
                result.extend(_split_recursive(part, max_size, remaining))
                buffer = ""
            else:
                buffer = part
    if buffer:
        result.append(buffer)
    return result


def recursive_chunk(text: str, max_chunk_size: int = 500) -> list[TextChunk]:
    separators = ["\n\n", "\n", ". ", " "]
    pieces = _split_recursive(text, max_chunk_size, separators)
    cleaned = [p.strip() for p in pieces if p.strip()]
    return [TextChunk(text=t, chunk_index=i) for i, t in enumerate(cleaned)]
