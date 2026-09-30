"""
Turn uploaded files into text that can be chunked and analysed.

Documents (PDF, Word, PowerPoint, Excel, HTML) are converted to Markdown with
Microsoft's MarkItDown, which keeps headings, lists and tables. Markdown and
text files are read directly; Obsidian syntax (front matter, [[wiki links]],
embeds, %%comments%%) is cleaned up. A .zip (for example an Obsidian vault) is
opened and every supported file inside it becomes its own document.

CSV and JSON files that contain one piece of feedback per row (a column such as
"feedback", "comment" or "message") are kept as rows, so customer and ARR
columns carry through to revenue-at-risk ranking.
"""
from __future__ import annotations

import csv
import io
import json
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 1000
MAX_ARCHIVE_TOTAL_BYTES = 200 * 1024 * 1024

MARKITDOWN_TYPES = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}
TEXT_TYPES = {".md", ".markdown", ".txt", ".text", ".log"}
TABLE_TYPES = {".csv", ".json"}
ARCHIVE_TYPES = {".zip"}
SUPPORTED_TYPES = MARKITDOWN_TYPES | TEXT_TYPES | TABLE_TYPES | ARCHIVE_TYPES

MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".log": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
}

# Column names that hold the feedback text / customer fields in exported tables
CONTENT_KEYS = ["content", "feedback", "comment", "comments", "message", "text", "review", "body", "description", "note", "notes", "summary", "subject"]
CUSTOMER_KEYS = ["customer_id", "customer", "account", "account_name", "company", "organization", "organisation", "client", "customer_name", "requester", "user", "email"]
ARR_KEYS = ["arr_value", "arr", "annual_revenue", "revenue", "contract_value", "acv"]
MRR_KEYS = ["mrr", "monthly_revenue"]
TIER_KEYS = ["customer_tier", "tier", "plan", "segment"]


class ExtractionError(Exception):
    """The file could not be read (unsupported, too large, corrupt, or no text)."""


@dataclass
class ExtractedDocument:
    path: str  # file name, or path inside a zip
    title: str
    mime_type: str
    kind: str = "document"  # document | note | table
    text: str = ""
    rows: List[Dict[str, Any]] = field(default_factory=list)


def extension_of(name: str) -> str:
    base = posixpath.basename(name.replace("\\", "/")).lower()
    return posixpath.splitext(base)[1]


def title_from_path(name: str) -> str:
    base = posixpath.basename(name.replace("\\", "/"))
    stem, _ = posixpath.splitext(base)
    return stem or base


def decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None:
            return str(best)
    except Exception:
        pass
    return data.decode("latin-1")


_FRONT_MATTER = re.compile(r"\A---\s*\n.*?\n(---|\.\.\.)\s*(\n|\Z)", re.DOTALL)
_OBSIDIAN_COMMENT = re.compile(r"%%.*?%%", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_EMBED = re.compile(r"!\[\[[^\]]*\]\]")
_WIKI_LINK = re.compile(r"\[\[([^\]|#]*)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")


def clean_markdown(text: str) -> str:
    """Remove Obsidian/Markdown syntax that is not part of what was said."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FRONT_MATTER.sub("", text, count=1)
    text = _OBSIDIAN_COMMENT.sub("", text)
    text = _HTML_COMMENT.sub("", text)
    text = _EMBED.sub("", text)
    text = _WIKI_LINK.sub(lambda m: (m.group(2) or posixpath.basename(m.group(1) or "")).strip(), text)
    return text.strip()


_markitdown = None


def _convert_with_markitdown(data: bytes, ext: str) -> str:
    global _markitdown
    if _markitdown is None:
        from markitdown import MarkItDown

        _markitdown = MarkItDown(enable_plugins=False)
    result = _markitdown.convert_stream(io.BytesIO(data), file_extension=ext)
    return (result.text_content or "").strip()


def _pick(row: Dict[str, Any], keys: List[str]) -> Optional[str]:
    lowered = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items() if k is not None}
    for key in keys:
        value = lowered.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _to_float(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", value)
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def rows_to_feedback(rows: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """
    If a table has one piece of feedback per row, map each row to the fields the
    normaliser understands. Returns None when no column looks like feedback text.
    """
    if not rows or not isinstance(rows[0], dict):
        return None
    if not any(_pick(row, CONTENT_KEYS) for row in rows[:50]):
        return None

    mapped = []
    for row in rows:
        content = _pick(row, CONTENT_KEYS)
        if not content:
            continue
        arr = _to_float(_pick(row, ARR_KEYS))
        if arr is None:
            mrr = _to_float(_pick(row, MRR_KEYS))
            arr = mrr * 12 if mrr is not None else None
        mapped.append(
            {
                "content": content,
                "customer_id": _pick(row, CUSTOMER_KEYS),
                "customer_tier": (_pick(row, TIER_KEYS) or "").lower() or None,
                "arr_value": arr,
                "source_type": str(row.get("source_type") or "spreadsheet_row"),
            }
        )
    return mapped


def _extract_table(name: str, data: bytes, ext: str) -> ExtractedDocument:
    title = title_from_path(name)
    text = decode_text(data)
    rows: Any = None
    if ext == ".json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ExtractionError(f"not valid JSON ({exc.msg})") from exc
        if isinstance(parsed, dict):
            # {"items": [...]} or a single record
            list_values = [v for v in parsed.values() if isinstance(v, list)]
            parsed = list_values[0] if len(list_values) == 1 else [parsed]
        rows = parsed if isinstance(parsed, list) else None
        feedback = rows_to_feedback(rows) if rows else None
        if feedback:
            return ExtractedDocument(path=name, title=title, mime_type=MIME_TYPES[ext], kind="table", rows=feedback)
        return ExtractedDocument(path=name, title=title, mime_type=MIME_TYPES[ext], text=json.dumps(parsed, indent=2, ensure_ascii=False))

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    feedback = rows_to_feedback(rows)
    if feedback:
        return ExtractedDocument(path=name, title=title, mime_type=MIME_TYPES[ext], kind="table", rows=feedback)
    # No feedback column: keep each row as a line of "column: value" pairs
    lines = [" · ".join(f"{k}: {v}" for k, v in row.items() if k and v not in (None, "")) for row in rows]
    return ExtractedDocument(path=name, title=title, mime_type=MIME_TYPES[ext], text="\n".join(line for line in lines if line))


def _extract_single(name: str, data: bytes) -> ExtractedDocument:
    ext = extension_of(name)
    title = title_from_path(name)
    if ext in TEXT_TYPES:
        kind = "note" if ext in {".md", ".markdown"} else "document"
        return ExtractedDocument(path=name, title=title, mime_type=MIME_TYPES[ext], kind=kind, text=clean_markdown(decode_text(data)))
    if ext in TABLE_TYPES:
        return _extract_table(name, data, ext)
    if ext in MARKITDOWN_TYPES:
        # MarkItDown sniffs content and would read a mislabelled or corrupt file as plain text
        if ext in {".docx", ".pptx", ".xlsx"} and not data.startswith(b"PK"):
            raise ExtractionError(f"could not read this {ext[1:].upper()} file (it is not a valid Office document)")
        if ext == ".pdf" and b"%PDF" not in data[:1024]:
            raise ExtractionError("could not read this PDF file (it is not a valid PDF)")
        try:
            text = _convert_with_markitdown(data, ext)
        except Exception as exc:
            raise ExtractionError(f"could not read this {ext[1:].upper()} file ({type(exc).__name__})") from exc
        return ExtractedDocument(path=name, title=title, mime_type=MIME_TYPES[ext], text=clean_markdown(text))
    raise ExtractionError(f"{ext or 'this file type'} is not supported")


def _skip_archive_member(member: str) -> bool:
    parts = [p for p in member.replace("\\", "/").split("/") if p]
    if not parts or parts[0] == "__MACOSX":
        return True
    # Hidden files and folders: .obsidian settings, .trash, .DS_Store, .git
    return any(p.startswith(".") for p in parts)


def _extract_archive(name: str, data: bytes) -> tuple[List[ExtractedDocument], List[Dict[str, str]]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ExtractionError("not a valid .zip file") from exc

    documents: List[ExtractedDocument] = []
    skipped: List[Dict[str, str]] = []
    members = [info for info in archive.infolist() if not info.is_dir() and not _skip_archive_member(info.filename)]
    if len(members) > MAX_ARCHIVE_ENTRIES:
        raise ExtractionError(f"the archive has {len(members)} files; the limit is {MAX_ARCHIVE_ENTRIES}")

    total = 0
    for info in members:
        ext = extension_of(info.filename)
        if ext not in SUPPORTED_TYPES or ext in ARCHIVE_TYPES:
            skipped.append({"path": info.filename, "reason": f"{ext or 'no extension'} is not supported"})
            continue
        if info.file_size > MAX_FILE_BYTES:
            skipped.append({"path": info.filename, "reason": "larger than 25 MB"})
            continue
        with archive.open(info) as handle:
            content = handle.read(MAX_FILE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_FILE_BYTES or total > MAX_ARCHIVE_TOTAL_BYTES:
            raise ExtractionError("the archive is larger than 200 MB once unpacked")
        try:
            documents.append(_extract_single(info.filename, content))
        except ExtractionError as exc:
            skipped.append({"path": info.filename, "reason": str(exc)})
    return documents, skipped


def extract_file(name: str, data: bytes) -> tuple[List[ExtractedDocument], List[Dict[str, str]]]:
    """
    Extract one uploaded file. Returns (documents, skipped entries). A zip gives
    one document per supported file inside it; anything else gives one document.
    Raises ExtractionError when the file itself cannot be used.
    """
    ext = extension_of(name)
    if ext not in SUPPORTED_TYPES:
        raise ExtractionError(f"{ext or 'files without an extension'} is not supported")
    if len(data) > MAX_FILE_BYTES:
        raise ExtractionError("larger than 25 MB")
    if ext in ARCHIVE_TYPES:
        return _extract_archive(name, data)
    return [_extract_single(name, data)], []
