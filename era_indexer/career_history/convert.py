"""Document conversion via Docling.

Docling produces structured markdown (preserves tables, reading order,
figure captions) for PDF / DOCX / PPTX / XLSX. Plain-text formats are
read directly to skip Docling overhead.
"""
from __future__ import annotations

import os
import time
from typing import Any

from rich.console import Console

from career_history import config


console = Console()


_converter: Any = None
_PLAIN_EXTS = {".md", ".txt"}

# Bump when conversion output semantics change (Docling upgrade, prompt change,
# OCR/caption policy change) so cached markdown is invalidated. The image model
# and OCR flag are folded into the per-file artifact_version at runtime.
CONVERT_VERSION = "docling-v2"


def _get_converter():
    global _converter
    if _converter is None:
        _converter = _build_converter()
    return _converter


def _build_converter():
    from docling.document_converter import DocumentConverter

    image_cfg = config.document_images()
    if not config.document_image_descriptions_enabled():
        console.log("[dim]Loading Docling converter...[/dim]")
        return DocumentConverter()

    format_options = _image_description_format_options(image_cfg)
    model = image_cfg.get("model", "qwen3-vl:8b")
    console.log(
        "[dim]Loading Docling converter with image descriptions "
        f"(model={model})...[/dim]"
    )
    return DocumentConverter(format_options=format_options)


def _image_description_format_options(image_cfg: dict[str, Any]) -> dict[Any, Any]:
    """Return Docling format options that caption extracted document images."""
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            ConvertPipelineOptions,
            PdfPipelineOptions,
            PictureDescriptionApiOptions,
        )
        from docling.document_converter import (
            ExcelFormatOption,
            PdfFormatOption,
            PowerpointFormatOption,
            WordFormatOption,
        )
    except ImportError as e:
        raise RuntimeError(
            "Docling image descriptions require a newer Docling version. "
            "Upgrade with `pip install -U docling`."
        ) from e

    picture_options = PictureDescriptionApiOptions(
        url=image_cfg.get("api_url", "http://localhost:11434/v1/chat/completions"),
        params={
            "model": image_cfg.get("model", "qwen3-vl:8b"),
            "seed": image_cfg.get("seed", 42),
            "max_completion_tokens": image_cfg.get("max_completion_tokens", 2000),
        },
        prompt=image_cfg.get("prompt") or _default_picture_prompt(),
        timeout=image_cfg.get("timeout_seconds", 180),
        concurrency=image_cfg.get("concurrency", 1),
    )

    pdf_options = PdfPipelineOptions()
    _configure_picture_pipeline(pdf_options, picture_options, image_cfg)

    convert_options = ConvertPipelineOptions()
    _configure_picture_pipeline(convert_options, picture_options, image_cfg)

    requested = {
        str(ext).lstrip(".").lower()
        for ext in image_cfg.get("formats", [".pdf", ".docx", ".pptx", ".xlsx"])
    }
    options: dict[Any, Any] = {}
    if "pdf" in requested:
        options[InputFormat.PDF] = PdfFormatOption(pipeline_options=pdf_options)
    if "docx" in requested:
        options[InputFormat.DOCX] = WordFormatOption(pipeline_options=convert_options)
    if "pptx" in requested:
        options[InputFormat.PPTX] = PowerpointFormatOption(
            pipeline_options=convert_options
        )
    if "xlsx" in requested:
        options[InputFormat.XLSX] = ExcelFormatOption(pipeline_options=convert_options)
    return options


def _configure_picture_pipeline(
    pipeline_options: Any,
    picture_options: Any,
    image_cfg: dict[str, Any],
) -> None:
    pipeline_options.do_picture_description = True
    pipeline_options.picture_description_options = picture_options
    pipeline_options.enable_remote_services = True
    if hasattr(pipeline_options, "do_ocr"):
        pipeline_options.do_ocr = config.document_image_ocr_enabled()
    if hasattr(pipeline_options, "generate_picture_images"):
        pipeline_options.generate_picture_images = image_cfg.get(
            "generate_picture_images", True
        )
    if hasattr(pipeline_options, "images_scale"):
        pipeline_options.images_scale = image_cfg.get("images_scale", 2.0)


def _default_picture_prompt() -> str:
    return (
        "Describe this image for a personal knowledge-base search index. "
        "Be detailed and factual. Capture visible text, diagrams, charts, "
        "tables, UI screenshots, workflows, entities, labels, and relationships. "
        "If the image is decorative or contains no useful information, say so briefly."
    )


def convert(file_path: str) -> str:
    """Return markdown text content for any supported document type."""
    ext = os.path.splitext(file_path)[1].lower()
    t0 = time.time()

    if ext in _PLAIN_EXTS:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    else:
        result = _get_converter().convert(file_path)
        content = result.document.export_to_markdown()

    console.log(
        f"[green]Converted[/green] {os.path.basename(file_path)} "
        f"({len(content)} chars, {time.time() - t0:.1f}s)"
    )
    return content


def _artifact_version() -> str:
    """Cache key suffix capturing what materially changes converted output."""
    img = config.document_images()
    ocr = int(config.document_image_ocr_enabled())
    if config.document_image_descriptions_enabled():
        return f"{CONVERT_VERSION}+img:{img.get('model', '?')}+ocr:{ocr}"
    return f"{CONVERT_VERSION}+noimg+ocr:{ocr}"


def convert_cached(file_id: int, file_path: str, source_hash: str) -> str:
    """Return converted markdown, using a persisted cache when available.

    Docling conversion (OCR + per-image vision captioning) is by far the slowest
    pipeline stage. Persisting its markdown keyed by the file's content hash lets
    re-embeds (e.g. after an embedding-model change) skip conversion entirely.
    Plain-text files are cheap, so they bypass the cache.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _PLAIN_EXTS:
        return convert(file_path)

    from career_history import db  # lazy import to avoid an import cycle at module load

    version = _artifact_version()
    cached = db.get_converted_markdown(file_id, source_hash, version)
    if cached is not None:
        console.log(
            f"[dim]Cache hit[/dim] {os.path.basename(file_path)} "
            "(converted markdown)"
        )
        return cached

    content = convert(file_path)
    if content and content.strip():
        db.put_converted_markdown(file_id, source_hash, version, content)
    return content
