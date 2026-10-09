"""Text chunking + Ollama embedding.

For audio, `chunk_segments` keeps speaker boundaries intact — a chunk never
crosses speakers, so every chunk in the DB can be attributed to one speaker.
For documents, `chunk_text` is a normal recursive-character split.
"""
from __future__ import annotations

import time
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from rich.console import Console

from career_history import config


console = Console()

_splitter: RecursiveCharacterTextSplitter | None = None
_embedder: OllamaEmbeddings | None = None


def _get_splitter() -> RecursiveCharacterTextSplitter:
    global _splitter
    if _splitter is None:
        cfg = config.get()["processing"]
        _splitter = RecursiveCharacterTextSplitter(
            chunk_size=cfg["chunk_size"],
            chunk_overlap=cfg["chunk_overlap"],
        )
    return _splitter


def _get_embedder() -> OllamaEmbeddings:
    global _embedder
    if _embedder is None:
        cfg = config.get()["models"]
        _embedder = OllamaEmbeddings(model=cfg["embedding_model"])
    return _embedder


def chunk_text(text: str) -> list[str]:
    """Split a document into chunks."""
    if not text or not text.strip():
        return []
    return _get_splitter().split_text(text)


def chunk_segments(segments: list[dict]) -> list[dict]:
    """Chunk a diarized transcript without crossing speaker boundaries.

    Each segment becomes one or more chunks, all attributed to that segment's
    speaker. Chunk content is prefixed with the speaker label so the embedded
    text contains the attribution.

    Returns: [{content, segment_index}, ...]
    """
    splitter = _get_splitter()
    chunk_size = config.get()["processing"]["chunk_size"]
    out: list[dict] = []
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        prefix = f"{seg['speaker']}: "
        if len(text) + len(prefix) <= chunk_size:
            out.append({"content": prefix + text, "segment_index": i})
        else:
            for part in splitter.split_text(text):
                out.append({"content": prefix + part, "segment_index": i})
    return out


DEFAULT_BATCH_SIZE = 32
MIN_CHARS = 500
RETRY_PAUSE_SECONDS = 2.0


def _embed_one(text: str) -> list[float]:
    """Embed a single chunk, halving it until Ollama accepts it."""
    while True:
        try:
            return _get_embedder().embed_documents([text])[0]
        except Exception:
            if len(text) <= MIN_CHARS:
                raise
            time.sleep(RETRY_PAUSE_SECONDS)
            text = text[: len(text) // 2]


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch; on failure (Ollama's runner can drop very large
    requests) retry in halves down to single chunks."""
    try:
        return _get_embedder().embed_documents(texts)
    except Exception:
        if len(texts) == 1:
            time.sleep(RETRY_PAUSE_SECONDS)
            return [_embed_one(texts[0])]
        time.sleep(RETRY_PAUSE_SECONDS)
        mid = len(texts) // 2
        return _embed_batch(texts[:mid]) + _embed_batch(texts[mid:])


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings via Ollama, in batches."""
    if not texts:
        return []
    t0 = time.time()
    size = int(config.get()["processing"].get("embed_batch_size") or DEFAULT_BATCH_SIZE)
    vectors: list[list[float]] = []
    for i in range(0, len(texts), size):
        vectors.extend(_embed_batch(texts[i:i + size]))
    console.log(
        f"[green]Embedded[/green] {len(texts)} chunks ({time.time() - t0:.1f}s)"
    )
    return vectors
