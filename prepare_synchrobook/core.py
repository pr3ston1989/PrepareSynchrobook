"""No server imports, credentials or network access in the interchange layer.

Nokturn contract: chapter_idx is EPUB spine order; para_idx counts all <p>.
Sentence offsets are UTF-16 code units, as in JavaScript String.slice().
Audio times are seconds from the beginning of the entire ordered audiobook.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from pathlib import Path
from . import __version__

AUDIO_EXTENSIONS = frozenset({".opus", ".mp3", ".m4b", ".m4a", ".ogg", ".flac"})
FORMAT = "nokturn-synchrobook"
SCHEMA = 1


class Cancelled(Exception):
    pass


def natural_key(name: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def audio_files(folder: Path) -> list[Path]:
    files = sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS),
                   key=lambda p: natural_key(p.name))
    if not files:
        raise ValueError("Wybrany katalog nie zawiera obsługiwanych plików audiobooka.")
    if len({p.name.casefold() for p in files}) != len(files):
        raise ValueError("Nazwy plików różnią się tylko wielkością liter.")
    return files


def sha256_file(path: Path, cancel=lambda: False) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            if cancel():
                raise Cancelled()
            digest.update(block)
    return digest.hexdigest()


def fingerprint(path: Path, cancel=lambda: False) -> dict:
    from mutagen import File
    before = path.stat()
    audio = File(path)
    duration = float(audio.info.length) if audio is not None else 0.0
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Nie można wiarygodnie odczytać długości: {path.name}")
    digest = sha256_file(path, cancel)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"Plik zmienił się podczas odczytu: {path.name}")
    return {"name": path.name, "bytes": after.st_size, "sha256": digest, "duration_sec": duration}


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def normalized_segment(segment: dict, duration: float) -> dict:
    text = re.sub(r"\s+", " ", str(segment["text"])).strip()
    start, end = float(segment["start"]), float(segment["end"])
    confidence = float(segment.get("confidence", 0.5))
    if not text or not all(math.isfinite(v) for v in (start, end, confidence)):
        raise ValueError("Pusty tekst albo nieprawidłowy czas rozpoznania.")
    if not 0 <= start < end <= duration + 0.25 or not 0 <= confidence <= 1:
        raise ValueError("Rozpoznany fragment wykracza poza plik audio.")
    words = []
    for word in segment.get("words", []):
        word_start, word_end = float(word["start"]), float(word["end"])
        if not math.isfinite(word_start) or not math.isfinite(word_end) or not 0 <= word_start <= word_end <= duration + .25:
            raise ValueError("Nieprawidłowy czas rozpoznanego słowa.")
        if str(word["word"]).strip():
            words.append({"word": str(word["word"]).strip(), "start": word_start, "end": min(word_end, duration)})
    return {"text": text, "start": start, "end": min(end, duration), "confidence": confidence, "words": words}


def make_package(project: dict) -> tuple[bytes, dict]:
    """Export anchors for the existing EPUB. Neither EPUB nor audio is uploaded."""
    from .alignment import align_project
    if not project.get("title", "").strip() or not project.get("chapters"):
        raise ValueError("Wpisz tytuł i przygotuj rozpoznawanie audiobooka.")
    timestamps, report, digest = align_project(project)
    manifest = {"format": FORMAT, "schema": SCHEMA, "generator": f"PrepareSynchrobook/{__version__}",
                "text_source": "existing-epub", "title": project["title"], "author": project.get("author", ""),
                "language": project.get("language", "pl"), "audio_files": [chapter["source"] for chapter in project["chapters"]],
                "epub_sha256": digest, "timestamps": timestamps}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, allow_nan=False))
    return buffer.getvalue(), {**manifest, "alignment_report": report}


def save_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)
