"""Match recognized audio words to the existing, unmodified publisher EPUB."""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path

from .alignment_engine import (_alignment_tokens, _align_words_to_paragraphs,
                               _densify_paragraph_alignment, _refine_sentence_alignment)


def epub_paragraphs(path: Path) -> tuple[list[dict], str]:
    from bs4 import BeautifulSoup
    from ebooklib import epub
    import ebooklib
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("EPUB jest większy niż 64 MiB.")
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 128 * 1024 * 1024:
            raise ValueError("EPUB po rozpakowaniu jest zbyt duży.")
    data = path.read_bytes()
    book = epub.read_epub(str(path), options={"ignore_ncx": True})
    items = [book.get_item_with_id(identifier) for identifier, _ in book.spine]
    items = [item for item in items if item and item.get_type() == ebooklib.ITEM_DOCUMENT]
    if not items:
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    paragraphs = []
    for chapter_idx, item in enumerate(items):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for para_idx, paragraph in enumerate(soup.find_all("p")):
            text = re.sub(r"\s+", " ", paragraph.get_text()).strip()
            if text:
                paragraphs.append({"chapter_idx": chapter_idx, "para_idx": para_idx, "text": text})
    if not paragraphs:
        raise ValueError("W EPUB nie znaleziono akapitów tekstu obsługiwanych przez synchronizację Nokturna.")
    if hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest():
        raise ValueError("EPUB zmienił się podczas odczytu.")
    return paragraphs, hashlib.sha256(data).hexdigest()


def align_project(project: dict) -> tuple[list[dict], dict, str]:
    path = Path(project.get("epub_file", ""))
    if not path.is_file():
        raise ValueError("Wskaż właściwy EPUB książki lub pobierz go z Nokturna. Transkrypcja nie zastępuje e-booka.")
    paragraphs, digest = epub_paragraphs(path)
    if project.get("epub_sha256") and project["epub_sha256"] != digest:
        raise ValueError("Wybrany EPUB różni się od tekstu użytego w tym projekcie. Wybierz oryginalny plik i ponów dopasowanie.")
    words = []
    offset = 0.0
    for chapter in project["chapters"]:
        for segment in chapter["segments"]:
            for word in segment.get("words", []):
                for token in _alignment_tokens(word["word"]):
                    words.append({"word": token, "start": offset + word["start"], "end": offset + word["end"]})
        offset += chapter["source"]["duration_sec"]
    if not words:
        raise ValueError("Brak rozpoznanych słów z czasami. Przygotuj rozpoznawanie ponownie.")
    timestamps = _align_words_to_paragraphs(words, paragraphs)
    timestamps = _densify_paragraph_alignment(words, paragraphs, timestamps)
    timestamps.sort(key=lambda stamp: (stamp["chapter_idx"], stamp["para_idx"]))
    # Drop ambiguous/non-monotonic anchors rather than inventing proportional times.
    safe = []
    previous_end = -1.0
    for stamp in timestamps:
        if stamp["confidence"] < .65 or stamp["start_sec"] <= previous_end:
            continue
        if not stamp["start_sec"] < stamp["end_sec"] <= offset + .05:
            continue
        stamp["end_sec"] = min(stamp["end_sec"], offset)
        safe.append(stamp)
        previous_end = stamp["start_sec"]
    for before, after in zip(safe, safe[1:]):
        before["end_sec"] = min(before["end_sec"], after["start_sec"])
    timestamps = _refine_sentence_alignment(words, paragraphs, safe)
    texts = {(p["chapter_idx"], p["para_idx"]): p["text"] for p in paragraphs}
    result = []
    for stamp in timestamps:
        text = texts[stamp["chapter_idx"], stamp["para_idx"]]
        sentences = []
        for start, end, time, confidence in stamp.get("sentences", []):
            if stamp["start_sec"] <= time <= stamp["end_sec"]:
                sentences.append([len(text[:start].encode("utf-16-le")) // 2,
                                  len(text[:end].encode("utf-16-le")) // 2, time, confidence])
        result.append({"chapter_idx": stamp["chapter_idx"], "para_idx": stamp["para_idx"],
                       "start_sec": stamp["start_sec"], "end_sec": stamp["end_sec"],
                       "confidence": stamp["confidence"], "interpolated": False, "sentences": sentences})
    if not result:
        raise ValueError("Nie znaleziono wiarygodnych dopasowań do EPUB. Sprawdź wydanie, język i jakość rozpoznawania. Nie utworzono fikcyjnej synchronizacji.")
    matched = {(s["chapter_idx"], s["para_idx"]) for s in result}
    total_chars = sum(len(p["text"]) for p in paragraphs)
    matched_chars = sum(len(p["text"]) for p in paragraphs if (p["chapter_idx"], p["para_idx"]) in matched)
    report = {"matched_paragraphs": len(result), "total_paragraphs": len(paragraphs),
              "text_coverage": round(matched_chars / max(total_chars, 1), 4),
              "unmatched": [{"chapter_idx": p["chapter_idx"], "para_idx": p["para_idx"], "text": p["text"][:250]}
                            for p in paragraphs if (p["chapter_idx"], p["para_idx"]) not in matched]}
    return result, report, digest
