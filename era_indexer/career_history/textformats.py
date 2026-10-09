"""Lightweight converters for text formats Docling doesn't handle.

- ``.srt`` / ``.vtt`` caption files: often the ready-made transcript sitting next
  to a meeting recording, so indexing them recovers the meeting content without
  running audio transcription.
- ``.eml`` emails: headers + body (plain text preferred, HTML stripped),
  attachment names listed.
"""
from __future__ import annotations

import email
import html
import os
import re
from email import policy
from html.parser import HTMLParser

_TIMING = re.compile(
    r"^\s*(\d{1,2}:)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
)
_TAG = re.compile(r"<[^>]+>")
PARAGRAPH_SECONDS = 60


def _seconds(match: re.Match[str]) -> int:
    hours = int((match.group(1) or "0:")[:-1] or 0)
    return hours * 3600 + int(match.group(2)) * 60 + int(match.group(3))


def _stamp(sec: int) -> str:
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def captions_to_markdown(text: str, title: str) -> str:
    """Merge caption cues into ~1-minute paragraphs, each prefixed with its start
    time. Cue numbers, timing lines, WEBVTT headers and markup are dropped, and a
    line identical to the previous one (rolling auto-captions) is skipped."""
    paragraphs: list[tuple[int, list[str]]] = []
    current_start: int | None = None
    current: list[str] = []
    cue_start = 0
    last_line = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.isdigit() or line.upper().startswith(("WEBVTT", "NOTE", "STYLE")):
            continue
        timing = _TIMING.match(line)
        if timing:
            cue_start = _seconds(timing)
            if current_start is not None and cue_start - current_start >= PARAGRAPH_SECONDS:
                paragraphs.append((current_start, current))
                current_start, current = None, []
            continue
        line = html.unescape(_TAG.sub("", line)).strip()
        if not line or line == last_line:
            continue
        last_line = line
        if current_start is None:
            current_start = cue_start
        current.append(line)
    if current_start is not None and current:
        paragraphs.append((current_start, current))

    out = [f"# Transcript: {title}", ""]
    for start, lines in paragraphs:
        out.append(f"[{_stamp(start)}] " + " ".join(lines))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in ("style", "script"):
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", text)).strip()


def eml_to_markdown(raw: bytes, title: str) -> str:
    msg = email.message_from_bytes(raw, policy=policy.default)
    out = [f"# Email: {msg.get('Subject') or title}", ""]
    for header in ("From", "To", "Cc", "Date", "Subject"):
        if msg.get(header):
            out.append(f"**{header}:** {msg.get(header)}")
    out.append("")

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        body = body_part.get_content()
        if body_part.get_content_type() == "text/html":
            body = _html_to_text(body)
        out.append(body.strip())

    attachments = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    # Inline signature images (image001.png ...) are noise.
    attachments = [a for a in attachments if not re.match(r"image\d+\.(png|jpe?g|gif)$", a, re.I)]
    if attachments:
        out += ["", "**Attachments:** " + ", ".join(attachments)]
    return "\n".join(out).rstrip() + "\n"


def convert_text_format(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    title = os.path.splitext(os.path.basename(file_path))[0]
    if ext == ".eml":
        with open(file_path, "rb") as f:
            return eml_to_markdown(f.read(), title)
    with open(file_path, encoding="utf-8-sig", errors="replace") as f:
        return captions_to_markdown(f.read(), title)


TEXT_FORMAT_EXTS = {".srt", ".vtt", ".eml"}
