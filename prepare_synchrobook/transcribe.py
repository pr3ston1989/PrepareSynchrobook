"""Local ASR; completed files are cached by full content hash and model settings."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .core import Cancelled, audio_files, fingerprint, normalized_segment, save_json


def prepare(folder: Path, output: Path, title: str, author: str, model_name="small",
            language="pl", notify=lambda text: None, cancel=lambda: False,
            model_factory=None, epub_file: Path | None = None) -> dict:
    from .alignment import epub_paragraphs
    if epub_file is None:
        raise ValueError("Wskaż właściwy EPUB; transkrypcja służy do dopasowania nagrania do jego tekstu.")
    _, epub_hash = epub_paragraphs(epub_file)
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "cache"
    cache.mkdir(exist_ok=True)
    files = audio_files(folder)
    notify("Sprawdzanie plików audio…")
    sources = []
    for path in files:
        if cancel():
            raise Cancelled()
        notify(f"Odczyt i sprawdzanie: {path.name}")
        sources.append(fingerprint(path, cancel))
    model = None
    chapters = []
    for index, (path, source) in enumerate(zip(files, sources)):
        if cancel():
            raise Cancelled()
        key = hashlib.sha256(json.dumps([source, model_name, language, "asr-words-v2"], sort_keys=True).encode()).hexdigest()
        cached = cache / f"{key}.json"
        segments = None
        if cached.exists():
            try:
                segments = [normalized_segment(s, source["duration_sec"]) for s in json.loads(cached.read_text(encoding="utf-8"))]
            except (ValueError, KeyError, TypeError):
                segments = None
        if segments is None:
            if model is None:
                notify(f"Ładowanie modelu {model_name}. Pierwsze uruchomienie pobiera model z internetu…")
                if model_factory is None:
                    from faster_whisper import WhisperModel
                    model_factory = WhisperModel
                model = model_factory(model_name, device="cpu", compute_type="int8")
            iterator, _ = model.transcribe(str(path), language=language, beam_size=5,
                                          word_timestamps=True, vad_filter=True,
                                          condition_on_previous_text=False)
            segments = []
            for segment in iterator:
                if cancel():
                    raise Cancelled()
                if segment.no_speech_prob >= 0.6 and segment.avg_logprob < -1:
                    continue
                confidence = min(1.0, max(0.0, math.exp(segment.avg_logprob)))
                if not segment.text.strip() or segment.end <= segment.start:
                    continue
                segments.append(normalized_segment({"text": segment.text, "start": segment.start,
                                                    "end": segment.end, "confidence": confidence,
                                                    "words": [{"word": word.word, "start": word.start, "end": word.end}
                                                              for word in (segment.words or [])]}, source["duration_sec"]))
                notify(f"{index + 1}/{len(files)} · {path.name} · {segment.end:.0f}/{source['duration_sec']:.0f} s")
            # Detect edits made while the model read the file, before trusting its timing.
            if fingerprint(path, cancel) != source:
                raise ValueError(f"Plik zmienił się w trakcie rozpoznawania: {path.name}")
            save_json(cached, segments)
        chapters.append({"source": source, "segments": segments})
        # Each completed file is durable, even if a later file fails or is cancelled.
        save_json(output / "draft.json", {"schema": 1, "title": title, "author": author,
                                         "language": language, "epub_file": str(epub_file.resolve()), "epub_sha256": epub_hash, "chapters": chapters})
    if audio_files(folder) != files:
        raise ValueError("Lista plików zmieniła się podczas pracy. Uruchom przygotowanie ponownie.")
    project = {"schema": 1, "title": title, "author": author, "language": language,
               "epub_file": str(epub_file.resolve()), "epub_sha256": epub_hash, "chapters": chapters}
    save_json(output / "project.json", project)
    return project
