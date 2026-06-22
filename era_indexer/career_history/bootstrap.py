"""Pre-download all models so subsequent runs work offline.

Run this once with internet access. Afterwards, all models are cached
locally (~/.cache/huggingface, ~/.cache/docling, Ollama's store) and the
pipeline works with no network.
"""
from __future__ import annotations

from rich.console import Console

from era import config
from era import transcribe


console = Console()


def bootstrap() -> None:
    cfg = config.get()
    console.rule("[bold]Bootstrap: pre-downloading all models")

    # ---- MLX Whisper (transcription only; no diarization) ----
    repo = transcribe._model_repo()
    console.log(f"→ MLX Whisper model ({repo})")
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(repo)
        console.log("   [green]ok[/green]")
    except Exception as e:
        console.log(
            f"[yellow]MLX Whisper model download skipped/failed: {e}\n"
            f"  It will be downloaded on first transcription instead.[/yellow]"
        )

    # ---- Docling ----
    console.log("→ Docling (layout + table models)")
    from docling.document_converter import DocumentConverter
    DocumentConverter()  # constructor triggers cache warmup of base models

    # ---- Ollama ----
    console.log("→ Ollama embedding model warmup")
    from langchain_ollama import OllamaEmbeddings
    model_name = cfg["models"]["embedding_model"]
    embedder = OllamaEmbeddings(model=model_name)
    try:
        embedder.embed_query("warmup")
        console.log(f"   [green]ok[/green] ({model_name})")
    except Exception as e:
        console.log(
            f"[yellow]Ollama warmup failed: {e}\n"
            f"  Run `ollama pull {model_name}` and make sure `ollama serve` is "
            f"running.[/yellow]"
        )

    console.rule("[bold green]Bootstrap complete. Safe to run offline.")
