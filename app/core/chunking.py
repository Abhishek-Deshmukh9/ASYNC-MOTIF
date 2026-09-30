"""
Split a document's text into passages for embedding and clustering.

Each passage should carry one idea, because clustering groups passages by topic:
a paragraph, a bullet point, a speaker's turn in a transcript, or a table row.
Very short pieces ("Thanks!", "Agenda") are joined onto the next piece, and long
ones are split at sentence boundaries so they fit the embedding model
(all-MiniLM-L6-v2 reads about 256 tokens, roughly 1,000 characters).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

MAX_CHARS = 900
MIN_CHARS = 20

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])\s+(?:\[[ xX]\]\s+)?")
_SPEAKER = re.compile(
    r"^\s*(?:\*\*|__)?([A-Z][\w.'’ -]{0,40}?)(?:\*\*|__)?\s*"
    r"(?:\(\d{1,2}:\d{2}(?::\d{2})?\)|\[\d{1,2}:\d{2}(?::\d{2})?\])?\s*:(?:\*\*|__)?\s+\S"
)
_EMPHASIS = re.compile(r"\*\*|__")
_LINE_END = re.compile(r"[.!?…\"”]\s*$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[\"'“‘(\[]?[A-Z0-9])")


@dataclass
class Chunk:
    text: str
    index: int
    section: Optional[str] = None
    speaker: Optional[str] = None


def _speaker_of(line: str) -> Optional[str]:
    match = _SPEAKER.match(line)
    if not match:
        return None
    name = match.group(1).strip()
    # "Note: ..." or "Action items: ..." are labels, not people; keep names short
    return name if len(name.split()) <= 4 else None


def _table_rows(lines: List[str]) -> List[str]:
    """Turn a Markdown table into one 'Header: value · Header: value' line per row."""
    cells = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines if not _TABLE_RULE.match(line)]
    if len(cells) < 2:
        return [" · ".join(c for c in row if c) for row in cells]
    header, body = cells[0], cells[1:]
    rows = []
    for row in body:
        pairs = [f"{h}: {v}" if h and h.lower() not in ("", "nan", "unnamed") else v for h, v in zip(header, row) if v and v.lower() != "nan"]
        if pairs:
            rows.append(" · ".join(pairs))
    return rows


def _blocks(text: str) -> Iterator[Tuple[str, Optional[str], Optional[str]]]:
    """Yield (block text, section heading, speaker) for each unit of meaning."""
    section: Optional[str] = None
    paragraph: List[str] = []

    def flush():
        nonlocal paragraph
        lines, paragraph = paragraph, []
        if not lines:
            return
        if sum(1 for line in lines if _TABLE_ROW.match(line)) >= 2:
            for row in _table_rows([line for line in lines if _TABLE_ROW.match(line)]):
                yield row, section, None
            return
        speakers = [_speaker_of(line) for line in lines]
        bullets = [bool(_BULLET.match(line)) for line in lines]
        # Slides and some notes put one complete sentence per line without bullet markers;
        # PDFs wrap sentences across lines. Lines that mostly end a sentence are separate items.
        line_items = len(lines) > 1 and sum(1 for line in lines if _LINE_END.search(line)) >= 0.6 * len(lines)
        if len(lines) > 1 and (sum(1 for s in speakers if s) >= 2 or sum(bullets) >= 2 or line_items):
            # A run of speaker turns, list items or one-sentence lines: each line (with its continuation lines) is a unit
            current: List[str] = []
            current_speaker: Optional[str] = None
            for line, speaker, bullet in zip(lines, speakers, bullets):
                if (speaker or bullet or line_items) and current:
                    yield " ".join(current), section, current_speaker
                    current, current_speaker = [], None
                if speaker:
                    current_speaker = speaker
                current.append(_BULLET.sub("", line).strip() if bullet else line.strip())
            if current:
                yield " ".join(current), section, current_speaker
            return
        joined = " ".join(_BULLET.sub("", line).strip() if bullet else line.strip() for line, bullet in zip(lines, bullets))
        yield joined, section, speakers[0]

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = _HEADING.match(raw_line)
        if heading:
            yield from flush()
            section = heading.group(2).strip() or section
            continue
        if not raw_line.strip():
            yield from flush()
            continue
        paragraph.append(raw_line)
    yield from flush()


def _split_long(text: str, max_chars: int) -> List[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: List[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            head, sentence = sentence[:cut].strip(), sentence[cut:].strip()
            if current:
                pieces.append(current)
                current = ""
            pieces.append(head)
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, max_chars: int = MAX_CHARS, min_chars: int = MIN_CHARS) -> List[Chunk]:
    """Split text into passages of one idea each, at most max_chars long."""
    chunks: List[Chunk] = []
    pending = ""  # short text waiting to be joined onto the next block
    pending_section: Optional[str] = None

    def emit(body: str, section: Optional[str], speaker: Optional[str]):
        for piece in _split_long(body, max_chars):
            piece = piece.strip()
            if piece:
                chunks.append(Chunk(text=piece, index=len(chunks), section=section, speaker=speaker))

    for block, section, speaker in _blocks(text):
        block = re.sub(r"\s+", " ", _EMPHASIS.sub("", block)).strip()
        if not block:
            continue
        if pending and pending_section != section:
            # Short text left over from the previous section: keep it only if it is a real passage
            if len(pending) >= min_chars:
                emit(pending, pending_section, None)
            pending = ""
        if len(block) < min_chars:
            # "Got it.", "Agenda": add to the previous passage in this section, or hold for the next one
            last = chunks[-1] if chunks else None
            if not pending and last is not None and last.section == section and len(last.text) + 1 + len(block) <= max_chars:
                last.text = f"{last.text} {block}"
            else:
                pending, pending_section = f"{pending} {block}".strip(), section
            continue
        body = f"{pending} {block}".strip() if pending else block
        pending = ""
        emit(body, section, speaker)

    if len(pending) >= min_chars:
        emit(pending, pending_section, None)
    return chunks
