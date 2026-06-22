"""Queue runner: drives each file through its pipeline stages.

State transitions:
    Audio:    pending → transcribing → chunking → embedding → done
    Document: pending → converting   → chunking → embedding → done
    Any:      → failed (with error_message + attempt_count++)

If the process dies mid-stage, the next `era run` finds the item still in a
non-terminal state and re-processes it from scratch. Re-processing is safe:
both `replace_chunks` and `replace_segments` wipe prior rows first.
"""
from __future__ import annotations

import os
import time
import traceback

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from era import config, convert, db, embed, filename, structure, transcribe


console = Console()


def run(
    folder: str | None = None,
    limit: int | None = None,
    run_settings: config.RunSettings | None = None,
) -> dict:
    """Process all pending queue items, optionally scoped to a folder."""
    settings = config.normalize_run_settings(run_settings)
    items = db.pending_files(folder=folder, limit=limit, run_settings=settings)
    if not items:
        console.log(f"[dim]Nothing pending for {settings['label']}.[/dim]")
        return {"processed": 0, "failed": 0}

    title = f"Processing {len(items)} {settings['label']} file(s)"
    if folder:
        title += f" in '{folder}'"
    console.rule(f"[bold]{title}[/bold]")

    processed = failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as prog:
        task = prog.add_task("indexing", total=len(items))
        for item in items:
            prog.update(task, description=f"[cyan]{item['file_name']}")
            try:
                _process_one(item)
                processed += 1
            except Exception as e:
                failed += 1
                err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                db.set_status(item["id"], "failed", error=err)
                console.log(f"[red]✗ {item['file_name']}[/red] — {e}")
            prog.advance(task)

    console.rule(
        f"[bold green]Done.[/bold green] processed={processed} failed={failed}"
    )
    return {"processed": processed, "failed": failed}


def _process_one(item: dict) -> None:
    """Run a single file through its full pipeline."""
    queue_id = item["id"]
    file_id = item["file_id"]
    file_path = item["file_path"]
    file_name = item.get("file_name")
    folder = item.get("folder")

    if item["is_audio"]:
        _process_audio(queue_id, file_id, file_path, file_name, folder)
    else:
        _process_document(
            queue_id, file_id, file_path, file_name, folder,
            file_hash=item.get("file_hash"),
        )


def _timed(stage_name: str, fn, *args, **kwargs):
    """Run fn, return (result, elapsed_seconds)."""
    t0 = time.time()
    result = fn(*args, **kwargs)
    return result, time.time() - t0


def _process_audio(
    queue_id: int,
    file_id: int,
    file_path: str,
    file_name: str | None = None,
    folder: str | None = None,
) -> None:
    # Stage: transcribe (includes diarization)
    db.set_status(queue_id, "transcribing")
    result, secs = _timed("transcribing", transcribe.transcribe, file_path)
    db.set_status(queue_id, "transcribing", stage="transcribing", stage_seconds=secs)

    segments = result["segments"]
    if not segments:
        db.set_status(queue_id, "done")
        return

    # Persist segments first so chunks can reference them.
    segment_ids = db.replace_segments(file_id, segments)

    # Stage: chunk
    db.set_status(queue_id, "chunking")
    seg_chunks, secs = _timed("chunking", embed.chunk_segments, segments)
    db.set_status(queue_id, "chunking", stage="chunking", stage_seconds=secs)

    if not seg_chunks:
        db.set_status(queue_id, "done")
        return

    # Build filename-aware context so audio chunks carry document identity in
    # both the embedded text and the keyword index, mirroring documents.
    file_name = file_name or os.path.basename(file_path)
    file_fields = filename.parse_filename(file_name)
    contextual_enabled = config.v2_enabled("contextual_embeddings_enabled")

    prepared = []
    for c in seg_chunks:
        speaker = segments[c["segment_index"]]["speaker"]
        metadata = {
            "kind": "audio",
            "speaker": speaker,
            "file_name": file_name,
            "file_path": file_path,
            "folder": folder,
            **structure._file_field_metadata(file_fields),
        }
        embedding_content = (
            structure.contextualize(c["content"], metadata)
            if contextual_enabled else c["content"]
        )
        prepared.append({
            "content": c["content"],
            "segment_index": c["segment_index"],
            "embedding_content": embedding_content,
            "search_text": structure._keyword_text(c["content"], metadata),
            "metadata": metadata,
        })

    # Stage: embed
    db.set_status(queue_id, "embedding")
    vectors, secs = _timed(
        "embedding", embed.embed, [c["embedding_content"] for c in prepared]
    )
    db.set_status(queue_id, "embedding", stage="embedding", stage_seconds=secs)

    chunks = [
        {
            "content": c["content"],
            "embedding": v,
            "segment_id": segment_ids[c["segment_index"]],
            "content_raw": c["content"],
            "embedding_content_version": (
                structure.EMBEDDING_CONTENT_VERSION if contextual_enabled
                else None
            ),
            "search_text": c["search_text"],
            "metadata": c["metadata"],
        }
        for c, v in zip(prepared, vectors)
    ]
    db.replace_chunks(file_id, chunks)
    db.set_status(queue_id, "done")


def _process_document(
    queue_id: int,
    file_id: int,
    file_path: str,
    file_name: str | None = None,
    folder: str | None = None,
    file_hash: str | None = None,
) -> None:
    # Stage: convert (uses the persisted markdown cache when the file content
    # is unchanged, so re-embeds skip the slow Docling/OCR/vision step).
    db.set_status(queue_id, "converting")
    if file_hash:
        text, secs = _timed(
            "converting", convert.convert_cached, file_id, file_path, file_hash
        )
    else:
        text, secs = _timed("converting", convert.convert, file_path)
    db.set_status(queue_id, "converting", stage="converting", stage_seconds=secs)

    if not text or not text.strip():
        db.set_status(queue_id, "done")
        return

    if config.v2_enabled("structure_aware_chunking_enabled"):
        _process_structured_document(
            queue_id, file_id, file_path, text, file_name, folder
        )
        return

    _process_flat_document(queue_id, file_id, text)


def _process_flat_document(queue_id: int, file_id: int, text: str) -> None:
    # Stage: chunk
    db.set_status(queue_id, "chunking")
    chunks_text, secs = _timed("chunking", embed.chunk_text, text)
    db.set_status(queue_id, "chunking", stage="chunking", stage_seconds=secs)

    if not chunks_text:
        db.set_status(queue_id, "done")
        return

    # Stage: embed
    db.set_status(queue_id, "embedding")
    vectors, secs = _timed("embedding", embed.embed, chunks_text)
    db.set_status(queue_id, "embedding", stage="embedding", stage_seconds=secs)

    chunks = [
        {
            "content": t,
            "embedding": v,
            "segment_id": None,
            "metadata": {"kind": "document"},
        }
        for t, v in zip(chunks_text, vectors)
    ]
    db.replace_chunks(file_id, chunks)
    db.set_status(queue_id, "done")


def _process_structured_document(
    queue_id: int,
    file_id: int,
    file_path: str,
    text: str,
    file_name: str | None = None,
    folder: str | None = None,
) -> None:
    # Stage: chunk with hierarchy extraction. Fall back to V1 chunking if
    # structure parsing fails so one unusual document does not block sync.
    db.set_status(queue_id, "chunking")
    try:
        structured, secs = _timed(
            "chunking",
            structure.build_document_chunks,
            text,
            file_path,
            file_name,
            folder,
        )
    except Exception as e:
        console.log(
            f"[yellow]Structure parsing failed; using flat chunking:[/yellow] {e}"
        )
        _process_flat_document(queue_id, file_id, text)
        return
    db.set_status(queue_id, "chunking", stage="chunking", stage_seconds=secs)

    structured_chunks = structured["chunks"]
    document = structured["document"]
    section_count = len(document.get("sections", []))
    console.log(
        "[green]Structured[/green] "
        f"{section_count} section(s), {len(structured_chunks)} chunk(s) "
        f"({document.get('structure_version')})"
    )
    if not structured_chunks:
        db.set_status(queue_id, "done")
        return

    # Stage: embed. The embedding text may be contextual while returned content
    # remains the raw chunk to preserve the existing search response contract.
    db.set_status(queue_id, "embedding")
    vectors, secs = _timed(
        "embedding",
        embed.embed,
        [c["embedding_content"] for c in structured_chunks],
    )
    db.set_status(queue_id, "embedding", stage="embedding", stage_seconds=secs)

    section_ids = db.replace_document_structure(file_id, document)
    parent_ids = db.replace_parent_chunks(
        file_id, structured.get("parents", []), section_ids
    )
    chunks = [
        {
            "content": c["content"],
            "embedding": v,
            "segment_id": None,
            "section_id": section_ids.get(c["section_local_id"]),
            "parent_chunk_id": parent_ids.get(c.get("parent_local_id"))
            if c.get("parent_local_id") is not None else None,
            "chunk_type": c["chunk_type"],
            "content_raw": c["content_raw"],
            "content_contextual": c["content_contextual"],
            "embedding_content_version": c["embedding_content_version"],
            "search_text": c.get("search_text"),
            "token_estimate": c["token_estimate"],
            "metadata": {
                **c["metadata"],
                "section_id": section_ids.get(c["section_local_id"]),
            },
        }
        for c, v in zip(structured_chunks, vectors)
    ]
    db.replace_chunks(file_id, chunks)
    db.set_status(queue_id, "done")
