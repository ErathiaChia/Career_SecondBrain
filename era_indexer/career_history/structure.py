"""Structure-aware document parsing and chunk construction.

The first V2 parser intentionally works from markdown because Docling already
exports documents that way, and plain markdown/text files can share the path.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from career_history import config, filename as filename_parser


STRUCTURE_VERSION = "markdown-headings-v1"
# Bumped when contextual (filename-aware) embedding text is produced so
# re-embedded chunks are distinguishable from raw-body-only chunks.
EMBEDDING_CONTENT_VERSION = "markdown-headings-ctx-v1"
# Used when an LLM situating blurb (Anthropic-style Contextual Retrieval) is also
# folded into the embedded text — a distinct version forces a clean re-embed.
EMBEDDING_CONTENT_VERSION_BLURB = "markdown-headings-ctx-blurb-v1"

# Field label, metadata key. Order controls how the context header reads.
_HEADER_FIELDS = [
    ("File", "file_name"),
    ("Client", "client"),
    ("Product", "product"),
    ("Doc type", "doc_type"),
    ("Version", "version"),
    ("Doc IDs", "doc_ids"),
    ("Folder", "folder"),
    ("Speaker", "speaker"),
    ("Document", "document_title"),
    ("Section", "section_path"),
    ("Chunk type", "chunk_type"),
]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


@dataclass
class _Section:
    local_id: int
    parent_local_id: int | None
    level: int
    title: str
    start_offset: int
    body_start_offset: int
    end_offset: int | None = None
    lines: list[str] = field(default_factory=list)
    path_titles: list[str] = field(default_factory=list)


def build_document_chunks(
    text: str,
    file_path: str,
    file_name: str | None = None,
    folder: str | None = None,
) -> dict[str, Any]:
    """Build document metadata, section rows, parent chunks, and child chunks.

    When parent-child retrieval is enabled each section body is first split into
    large parent chunks; each parent is then split into small child chunks. Only
    children are embedded (precise matching); the parent is returned at query
    time for context. When disabled, chunks are a single level (parent_local_id
    stays None) and ``parents`` is empty.
    """
    file_name = file_name or os.path.basename(file_path)
    title_hint = os.path.splitext(file_name)[0]
    sections = _parse_sections(text, title_hint)
    document_title = _document_title(sections, title_hint)
    file_fields = filename_parser.parse_filename(file_name)

    contextual_enabled = config.v2_enabled("contextual_embeddings_enabled")
    parent_child_enabled = config.v2_enabled("parent_child_retrieval_enabled")
    # LLM situating blurb only makes sense when contextual embeddings are on
    # (the blurb is folded into the contextual embedding text).
    blurb_enabled = contextual_enabled and config.v2_enabled("contextual_llm_blurb_enabled")
    child_splitter = _child_splitter() if parent_child_enabled else _splitter()
    parent_splitter = _parent_splitter() if parent_child_enabled else None

    chunks: list[dict[str, Any]] = []
    parents: list[dict[str, Any]] = []
    parent_seq = 0

    def _make_child(
        raw_chunk: str,
        section: _Section,
        parent_local_id: int | None,
        context_text: str = "",
    ) -> None:
        chunk_type = _chunk_type(raw_chunk)
        metadata = {
            "kind": "document",
            "file_name": file_name,
            "file_path": file_path,
            "folder": folder,
            "document_title": document_title,
            "section_title": _section_title(section),
            "subsection_title": _subsection_title(section),
            "section_path": " > ".join(section.path_titles),
            "chunk_type": chunk_type,
            "structure_status": "structured",
            "structure_version": STRUCTURE_VERSION,
            **_file_field_metadata(file_fields),
        }
        blurb = _situating_blurb(raw_chunk, context_text, metadata) if blurb_enabled else ""
        if blurb:
            metadata["llm_context"] = blurb
        contextual = contextualize(raw_chunk, metadata, blurb=blurb)
        chunks.append({
            "content": raw_chunk,
            "content_raw": raw_chunk,
            "content_contextual": contextual,
            "embedding_content": contextual if contextual_enabled else raw_chunk,
            "embedding_content_version": (
                EMBEDDING_CONTENT_VERSION_BLURB if (contextual_enabled and blurb)
                else EMBEDDING_CONTENT_VERSION if contextual_enabled
                else STRUCTURE_VERSION
            ),
            "search_text": _keyword_text(raw_chunk, metadata, blurb=blurb),
            "chunk_type": chunk_type,
            "section_local_id": section.local_id,
            "parent_local_id": parent_local_id,
            "metadata": metadata,
            "token_estimate": _token_estimate(raw_chunk),
        })

    for section in sections:
        body = "\n".join(section.lines).strip()
        if not body:
            continue

        if parent_child_enabled and parent_splitter is not None:
            for parent_text in parent_splitter.split_text(body):
                parent_local_id = parent_seq
                parent_seq += 1
                parents.append({
                    "local_id": parent_local_id,
                    "section_local_id": section.local_id,
                    "ordinal": parent_local_id,
                    "content": parent_text,
                    "token_estimate": _token_estimate(parent_text),
                    "metadata": {
                        "section_path": " > ".join(section.path_titles),
                        "document_title": document_title,
                    },
                })
                for raw_chunk in child_splitter.split_text(parent_text):
                    _make_child(raw_chunk, section, parent_local_id, context_text=parent_text)
        else:
            for raw_chunk in child_splitter.split_text(body):
                _make_child(raw_chunk, section, None, context_text=body)

    return {
        "document": {
            "title": document_title,
            "structure_version": STRUCTURE_VERSION,
            "parse_metadata": {
                "section_count": len(sections),
                "chunk_count": len(chunks),
                "parent_count": len(parents),
                "parser": "markdown",
            },
            "sections": [_section_row(s) for s in sections],
        },
        "parents": parents,
        "chunks": chunks,
    }


def contextualize(raw_chunk: str, metadata: dict[str, Any], blurb: str = "") -> str:
    """Return contextual text used for optional contextual embeddings.

    Prepends a compact, labeled context header (filename-derived fields,
    folder, document title, section path, chunk type) to the raw chunk so the
    embedding carries document identity, not just the body text. When ``blurb``
    is provided (an LLM situating sentence, Anthropic-style Contextual
    Retrieval), it is prepended ahead of the header. Empty fields are omitted to
    keep the prefix short and avoid diluting the embedding.
    """
    body = raw_chunk.strip()
    prefix_parts: list[str] = []
    if blurb:
        prefix_parts.append(f"Context: {blurb}")
    header = _context_header(metadata)
    if header:
        prefix_parts.append(header)
    if not prefix_parts:
        return body
    return f"{chr(10).join(prefix_parts)}\n\nContent:\n{body}"


def _context_header(metadata: dict[str, Any]) -> str:
    lines = []
    for label, key in _HEADER_FIELDS:
        value = metadata.get(key)
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


_BLURB_PROMPT = """You are indexing a personal knowledge base. Write a SHORT \
context (1-2 sentences, at most 40 words) that situates the chunk below within \
its document, so the chunk can be understood and retrieved on its own.

Document: {doc_title}
Section: {section}

Surrounding context:
{context}

Chunk:
{chunk}

Rules:
- State what the chunk is about and how it relates to the document/section.
- Use concrete names (client, product, project, people) when they appear.
- Do NOT introduce facts not present in the text. Do NOT repeat the chunk.
- Output ONLY the context sentence(s), with no preamble or labels."""


def _blurb_llm_settings() -> tuple[str, str]:
    """Resolve (model, base_url) for the situating-blurb LLM.

    Mirrors graph._extract_with_ollama so both run on the same Mac Ollama by
    default; a dedicated ``models.contextual_blurb_model`` overrides the graph
    model when set.
    """
    cfg = config.get()
    model = (
        os.environ.get("ERA_CONTEXTUAL_BLURB_MODEL")
        or cfg.get("models", {}).get("contextual_blurb_model")
        or cfg.get("models", {}).get("graph_extraction_model")
        or "qwen3.5:9b-mlx"
    )
    base_url = (
        os.environ.get("OLLAMA_BASE_URL")
        or config.v2().get("graph_ollama_base_url")
        or "http://localhost:11434"
    ).rstrip("/")
    return model, base_url


def _situating_blurb(raw_chunk: str, context_text: str, metadata: dict[str, Any]) -> str:
    """Return a 1-2 sentence LLM blurb situating the chunk within its document.

    Anthropic-style Contextual Retrieval: the blurb is prepended to the embedded
    (and keyword-indexed) text so each chunk carries where-it-sits context. Best
    effort — returns "" on any LLM/transport failure so embedding still proceeds.
    """
    if not raw_chunk.strip():
        return ""
    model, base_url = _blurb_llm_settings()
    prompt = _BLURB_PROMPT.format(
        doc_title=metadata.get("document_title") or metadata.get("file_name") or "",
        section=metadata.get("section_path") or "",
        context=(context_text or "")[:4000],
        chunk=raw_chunk[:2000],
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return ""
    return (body.get("response") or "").strip()


def _keyword_text(raw_chunk: str, metadata: dict[str, Any], blurb: str = "") -> str:
    """Build the FTS source text: filename-derived terms + raw body.

    Folding filename fields into the keyword channel lets lexical queries match
    on client, product, doc type, version, etc. even when those terms never
    appear in the chunk body. When present, the LLM situating ``blurb`` is also
    folded in so the lexical channel benefits from the same added context.
    """
    parts: list[str] = []
    if blurb:
        parts.append(blurb)
    for key in (
        "clean_name", "client", "product", "topic", "doc_type",
        "version", "doc_ids", "document_title", "section_path", "folder",
    ):
        value = metadata.get(key)
        if value:
            parts.append(str(value))
    context = " ".join(parts).strip()
    return f"{context}\n{raw_chunk}" if context else raw_chunk


def _file_field_metadata(file_fields: dict[str, Any]) -> dict[str, Any]:
    """Select filename-derived fields worth storing on each chunk's metadata."""
    keys = (
        "client", "product", "topic", "doc_type", "version",
        "doc_ids", "originator", "clean_name",
    )
    return {k: file_fields[k] for k in keys if file_fields.get(k)}


def _splitter() -> RecursiveCharacterTextSplitter:
    cfg = config.get()["processing"]
    return RecursiveCharacterTextSplitter(
        chunk_size=cfg["chunk_size"],
        chunk_overlap=cfg["chunk_overlap"],
    )


def _parent_splitter() -> RecursiveCharacterTextSplitter:
    cfg = config.get()["processing"]
    return RecursiveCharacterTextSplitter(
        chunk_size=cfg.get("parent_chunk_size", 2400),
        chunk_overlap=cfg.get("parent_chunk_overlap", 200),
    )


def _child_splitter() -> RecursiveCharacterTextSplitter:
    cfg = config.get()["processing"]
    return RecursiveCharacterTextSplitter(
        chunk_size=cfg.get("child_chunk_size", 600),
        chunk_overlap=cfg.get("child_chunk_overlap", 120),
    )


def _parse_sections(text: str, title_hint: str) -> list[_Section]:
    lines = text.splitlines()
    sections: list[_Section] = []
    stack: list[_Section] = []
    current: _Section | None = None
    offset = 0

    def close_open_sections(end_offset: int, min_level: int = 1) -> None:
        while stack and stack[-1].level >= min_level:
            closing = stack.pop()
            if closing.end_offset is None:
                closing.end_offset = end_offset

    def open_section(level: int, title: str, start: int, body_start: int) -> _Section:
        nonlocal current
        close_open_sections(start, level)
        parent = stack[-1] if stack else None
        path_titles = [*(parent.path_titles if parent else []), title]
        section = _Section(
            local_id=len(sections),
            parent_local_id=parent.local_id if parent else None,
            level=level,
            title=title,
            start_offset=start,
            body_start_offset=body_start,
            path_titles=path_titles,
        )
        sections.append(section)
        stack.append(section)
        current = section
        return section

    for line in lines:
        line_start = offset
        offset += len(line) + 1
        match = _HEADING_RE.match(line.strip())
        if match:
            level = len(match.group(1))
            title = _clean_title(match.group(2))
            open_section(level, title, line_start, offset)
            continue

        if current is None:
            current = open_section(1, title_hint or "Document", 0, 0)
        current.lines.append(line)

    close_open_sections(offset, 1)
    if not sections:
        sections.append(_Section(
            local_id=0,
            parent_local_id=None,
            level=1,
            title=title_hint or "Document",
            start_offset=0,
            body_start_offset=0,
            end_offset=len(text),
            lines=lines,
            path_titles=[title_hint or "Document"],
        ))

    for section in sections:
        if section.end_offset is None:
            section.end_offset = len(text)
    return sections


def _document_title(sections: list[_Section], title_hint: str) -> str:
    for section in sections:
        if section.level == 1 and section.title:
            return section.title
    return title_hint or "Untitled Document"


def _section_title(section: _Section) -> str:
    return section.path_titles[0] if section.path_titles else section.title


def _subsection_title(section: _Section) -> str | None:
    return section.path_titles[-1] if len(section.path_titles) > 1 else None


def _section_row(section: _Section) -> dict[str, Any]:
    return {
        "local_id": section.local_id,
        "parent_local_id": section.parent_local_id,
        "level": section.level,
        "title": section.title,
        "section_path": " > ".join(section.path_titles),
        "ordinal": section.local_id,
        "start_offset": section.start_offset,
        "end_offset": section.end_offset,
        "metadata": {
            "body_start_offset": section.body_start_offset,
            "structure_version": STRUCTURE_VERSION,
        },
    }


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def _chunk_type(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "paragraph"
    table_lines = sum(1 for line in lines if "|" in line)
    list_lines = sum(1 for line in lines if _LIST_RE.match(line))
    if table_lines >= max(2, len(lines) // 2):
        return "table"
    if list_lines >= max(2, len(lines) // 2):
        return "list"
    return "paragraph"


def _token_estimate(text: str) -> int:
    # Cheap local estimate good enough for monitoring token growth.
    return max(1, len(text) // 4)
