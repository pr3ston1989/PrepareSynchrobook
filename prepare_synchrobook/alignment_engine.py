"""Pure alignment routines from Nokturn vosk_sync.py (f83d547).
No database, media, server or model imports. Kept compatible with Nokturn anchors.
"""
import re
import math
from bisect import bisect_left, bisect_right
from typing import List, Optional

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?…]+[\"'»”’)\]]*(?=\s)")

_SENTENCE_ABBREVIATIONS = frozenset({
    "np", "itd", "itp", "tzn", "tj", "in", "ok", "por", "zob", "ww", "tzw",
    "dr", "prof", "inz", "mgr", "hab", "red", "gen", "plk", "sw", "ks",
    "ul", "al", "godz", "min", "sek", "str", "nr", "poz", "rys", "tab",
    "r", "w", "s", "t", "z", "pkt", "art", "ust", "wyd",
})

MIN_SENTENCE_CHARS = 24

_ALIGNMENT_TOKEN_RE = re.compile(r"[0-9a-ząćęłńóśźż]+", re.IGNORECASE)
_ALIGNMENT_TRANSLATION = str.maketrans("ąćęłńóśźż", "acelnoszz")

def _alignment_tokens(value: str) -> List[str]:
    """Normalize Polish text into comparable Vosk/EPUB tokens."""
    return [
        token.casefold().translate(_ALIGNMENT_TRANSLATION)
        for token in _ALIGNMENT_TOKEN_RE.findall(value or "")
    ]

def _alignment_word_score(recognized: str, expected: str) -> float:
    """Score one word while tolerating a single Polish inflection ending."""
    if recognized == expected:
        return 1.0
    if min(len(recognized), len(expected)) >= 5 and recognized[:4] == expected[:4]:
        return 0.75
    return 0.0

def _alignment_candidate_score(
    words: List[str],
    start_index: int,
    anchor_tokens: List[str],
) -> tuple[float, int, int]:
    """Score an ordered phrase, allowing short gaps caused by recognition noise."""
    cursor = start_index
    matched = 0
    score = 0.0
    for expected in anchor_tokens:
        match_index = None
        match_score = 0.0
        for index in range(cursor, min(cursor + 4, len(words))):
            candidate_score = _alignment_word_score(words[index], expected)
            if candidate_score > match_score:
                match_index = index
                match_score = candidate_score
        if match_index is None:
            continue
        matched += 1
        score += match_score
        cursor = match_index + 1
    return score / max(len(anchor_tokens), 1), matched, cursor

def _is_abbreviation_boundary(text: str, boundary: int) -> bool:
    """Czy kropka na `boundary` należy do skrótu, a nie do końca zdania."""
    head = text[:boundary].rstrip("\"'»”’)]")
    if not head.endswith((".",)):
        return False
    word_tokens = _ALIGNMENT_TOKEN_RE.findall(head[:-1])
    if not word_tokens:
        return False
    last = word_tokens[-1].casefold().translate(_ALIGNMENT_TRANSLATION)
    # Jednoliterowy człon to inicjał ("A. Kowalski") albo część "m.in.".
    return len(last) <= 1 or last in _SENTENCE_ABBREVIATIONS

def _split_sentences(text: str) -> List[tuple[int, int, str]]:
    """Dzieli akapit na zdania jako (char_start, char_end, tekst).

    Offsety liczone są względem znormalizowanego tekstu akapitu, tego samego,
    który czytnik odtwarza z DOM. Dzięki temu przód może zamienić zakres znaków
    na zakres w węzłach tekstowych bez zgadywania.
    """
    if not text:
        return []

    spans: List[tuple[int, int, str]] = []
    start = 0

    def extend_previous(end: int) -> None:
        previous_start = spans[-1][0]
        spans[-1] = (previous_start, end, text[previous_start:end].strip())

    for match in _SENTENCE_BOUNDARY_RE.finditer(text):
        boundary = match.end()
        if _is_abbreviation_boundary(text, boundary):
            continue
        following = text[boundary:].lstrip()
        # Mała litera po kropce znaczy, że to nie był koniec zdania.
        if following and following[0].islower():
            continue
        candidate = text[start:boundary].strip()
        if not candidate:
            start = boundary
            continue
        if len(candidate) < MIN_SENTENCE_CHARS:
            if spans:
                extend_previous(boundary)
                start = boundary
            # Krótki fragment na początku akapitu nie ma czego przedłużyć,
            # więc zostawiamy `start` i dołączy do następnego zdania.
            continue
        spans.append((start, boundary, candidate))
        start = boundary

    tail = text[start:].strip()
    if tail:
        if len(tail) < MIN_SENTENCE_CHARS and spans:
            extend_previous(len(text))
        else:
            spans.append((start, len(text), tail))

    return spans

def _bounded_alignment_candidate_score(
    words: List[str],
    start_index: int,
    anchor_tokens: List[str],
    *,
    window_end: int,
    lookahead: int,
) -> tuple[float, int, int]:
    """Score a fallback phrase without reading beyond its paragraph window."""
    cursor = start_index
    matched = 0
    score = 0.0
    limit = min(max(int(window_end), 0), len(words))
    for expected in anchor_tokens:
        match_index = None
        match_score = 0.0
        for index in range(cursor, min(cursor + lookahead, limit)):
            candidate_score = _alignment_word_score(words[index], expected)
            if candidate_score > match_score:
                match_index = index
                match_score = candidate_score
        if match_index is None:
            continue
        matched += 1
        score += match_score
        cursor = match_index + 1
    return score / max(len(anchor_tokens), 1), matched, cursor

def _align_sentences_within(
    recognized_tokens: List[str],
    window_start: int,
    window_end: int,
    sentence_groups: List[List[str]],
    *,
    diagnostics: Optional[List[dict]] = None,
) -> List[tuple[int, float] | None]:
    """Znajduje początek każdego zdania wewnątrz okna słów danego akapitu.

    Akapit jest już dopasowany, więc nie szukamy go ponownie — ustalamy tylko
    granice zdań, przechodząc okno monotonicznie. Zdanie, którego nie da się
    umiejscowić pewnie, zostaje bez kotwicy, zamiast dostać zgadniętą.

    Najpierw działa dotychczasowa ścisła ścieżka. Dopiero po jej porażce dwa
    zmierzone fallbacki zachowują te same progi matched/score: późniejsze zdanie
    może zacząć się od drugiego anchora, gdy pierwszego naprawdę nie ma w ASR,
    albo użyć lookahead 8 zamiast 4 przy rozpoznanym pierwszym anchorze. Oba
    fallbacki są ograniczone prawą granicą okna akapitu. Pierwsze zdanie nie
    korzysta z późnego drugiego anchora — jego bezpiecznym czasem pozostaje
    początek akapitu dodawany przez `_refine_sentence_alignment`.
    """
    placements: List[tuple[int, float] | None] = []
    cursor = window_start

    for sentence_index, tokens in enumerate(sentence_groups):
        anchors = [token for token in tokens if len(token) >= 4][:6]
        trace = {
            "sentence_index": sentence_index,
            "anchor_tokens": anchors,
            "window_start": window_start,
            "window_end": window_end,
            "window_word_count": max(0, window_end - window_start),
            "cursor": cursor,
            "required_matches": None,
            "first_anchor_candidates": 0,
            "best_index": None,
            "best_matched": 0,
            "best_score": 0.0,
        } if diagnostics is not None else None

        if len(anchors) < 2:
            placements.append(None)
            if trace is not None:
                trace["reason"] = "too_few_anchor_tokens"
                diagnostics.append(trace)
            continue
        if cursor >= window_end:
            placements.append(None)
            if trace is not None:
                trace["reason"] = "cursor_exhausted"
                diagnostics.append(trace)
            continue

        required_matches = max(2, math.ceil(len(anchors) * 0.6))
        if trace is not None:
            trace["required_matches"] = required_matches

        # Ścisła ścieżka pozostaje bit-for-bit taka jak przed naprawą.
        strict_best: tuple[float, int] | None = None
        strict_first_anchor_candidates = 0
        for index in range(cursor, window_end):
            if _alignment_word_score(recognized_tokens[index], anchors[0]) <= 0:
                continue
            strict_first_anchor_candidates += 1
            score, matched, _cursor = _alignment_candidate_score(
                recognized_tokens, index, anchors
            )
            if matched < required_matches or score < 0.55:
                continue
            if strict_best is None or score > strict_best[0]:
                strict_best = (score, index)

        original_reason: Optional[str] = None
        if trace is not None:
            best_observed: tuple[float, int, int] | None = None
            candidate_with_required_matches = False
            for diagnostic_index in range(cursor, window_end):
                if _alignment_word_score(
                    recognized_tokens[diagnostic_index], anchors[0]
                ) <= 0:
                    continue
                diagnostic_score, diagnostic_matched, _diagnostic_cursor = (
                    _alignment_candidate_score(
                        recognized_tokens, diagnostic_index, anchors
                    )
                )
                if (
                    best_observed is None
                    or diagnostic_score > best_observed[0]
                    or (
                        diagnostic_score == best_observed[0]
                        and diagnostic_matched > best_observed[1]
                    )
                ):
                    best_observed = (
                        diagnostic_score,
                        diagnostic_matched,
                        diagnostic_index,
                    )
                if diagnostic_matched >= required_matches:
                    candidate_with_required_matches = True

            trace["first_anchor_candidates"] = strict_first_anchor_candidates
            if best_observed is not None:
                trace["best_score"] = round(best_observed[0], 3)
                trace["best_matched"] = best_observed[1]
                trace["best_index"] = best_observed[2]
            if strict_best is None:
                if strict_first_anchor_candidates == 0:
                    original_reason = "no_first_anchor_candidate"
                elif not candidate_with_required_matches:
                    original_reason = "matches_below_required"
                else:
                    original_reason = "score_below_threshold"

        best = strict_best
        match_strategy = "strict"

        # Pomiar 16854: 72,7% braków pierwszego anchora ma wystarczająco silną
        # pozostałą sekwencję. Dla późniejszych zdań zaczynamy konserwatywnie na
        # DRUGIM anchorze (nie dowolnym dalszym), nadal wymagając tej samej liczby
        # trafień i tego samego score. Czas jest przez to co najwyżej odrobinę
        # spóźniony, nigdy zgadnięty przed pierwszym rozpoznanym słowem zdania.
        if (
            best is None
            and strict_first_anchor_candidates == 0
            and sentence_index > 0
            and len(anchors) >= 3
        ):
            suffix_length = len(anchors) - 1
            for index in range(cursor, window_end):
                if _alignment_word_score(
                    recognized_tokens[index], anchors[1]
                ) <= 0:
                    continue
                suffix_score, matched, _suffix_cursor = (
                    _bounded_alignment_candidate_score(
                        recognized_tokens,
                        index,
                        anchors[1:],
                        window_end=window_end,
                        lookahead=4,
                    )
                )
                score = suffix_score * suffix_length / len(anchors)
                if matched < required_matches or score < 0.55:
                    continue
                if best is None or score > best[0]:
                    best = (score, index)
                    match_strategy = "missing_first_anchor"

        # Drugi zmierzony przypadek to sekwencja z poprawnym początkiem, ale z
        # ponad trzema słowami szumu ASR pomiędzy anchorami. Lookahead 8 działa
        # wyłącznie jako fallback, w tym samym oknie i przy niezmienionych progach.
        if best is None and strict_first_anchor_candidates > 0:
            for index in range(cursor, window_end):
                if _alignment_word_score(
                    recognized_tokens[index], anchors[0]
                ) <= 0:
                    continue
                score, matched, _fallback_cursor = (
                    _bounded_alignment_candidate_score(
                        recognized_tokens,
                        index,
                        anchors,
                        window_end=window_end,
                        lookahead=8,
                    )
                )
                if matched < required_matches or score < 0.55:
                    continue
                if best is None or score > best[0]:
                    best = (score, index)
                    match_strategy = "lookahead_8"

        if best is None:
            placements.append(None)
            if trace is not None:
                trace["reason"] = original_reason or "unmatched"
                diagnostics.append(trace)
            continue

        score, index = best
        placements.append((index, score))
        cursor = index + 1
        if trace is not None:
            trace.update({
                "reason": "matched",
                "match_strategy": match_strategy,
                "recovered_from_reason": (
                    original_reason if match_strategy != "strict" else None
                ),
                "accepted_index": index,
                "accepted_score": round(score, 3),
                "next_cursor": cursor,
            })
            diagnostics.append(trace)

    return placements

def _refine_sentence_alignment(
    words: List[dict],
    epub_paragraphs: List[dict],
    timestamps: List[dict],
    *,
    diagnostics: Optional[List[dict]] = None,
) -> List[dict]:
    """Dokłada kotwice zdaniowe do już dopasowanych akapitów.

    Zdania trafiają do zagnieżdżonej listy `sentences` w formacie
    `[char_start, char_end, start_sec, confidence]`. Zagnieżdżenie, a nie osobne
    wpisy, jest tu celowe: czytnik przeszukuje listę akapitów przy każdej
    zmianie pozycji audio, a rozdmuchanie jej kilkukrotnie spowolniłoby to,
    co użytkownik i tak odczuwa jako mulenie.

    Opcjonalny kolektor diagnostyczny zapisuje przyczyny odrzuceń, ale nie jest
    częścią produkcyjnego wyniku synchronizacji i nie zmienia jej zachowania.
    """
    if not words or not timestamps or not epub_paragraphs:
        return timestamps

    recognized_tokens = [
        tokens[0] if tokens else ""
        for tokens in (_alignment_tokens(str(word.get("word", ""))) for word in words)
    ]
    word_starts = [float(word.get("start", 0.0)) for word in words]
    paragraphs = {
        (int(paragraph["chapter_idx"]), int(paragraph["para_idx"])): paragraph
        for paragraph in epub_paragraphs
    }

    for timestamp in timestamps:
        chapter_idx = int(timestamp["chapter_idx"])
        para_idx = int(timestamp["para_idx"])
        paragraph_trace = {
            "chapter_idx": chapter_idx,
            "para_idx": para_idx,
            "dense": bool(timestamp.get("dense")),
            "interpolated": bool(timestamp.get("interpolated")),
            "start_sec": float(timestamp["start_sec"]),
            "end_sec": float(timestamp["end_sec"]),
            "sentence_count": 0,
            "matched_placements": 0,
            "stored_count": 0,
            "forced_first_fallback": False,
            "sentence_diagnostics": [],
        } if diagnostics is not None else None
        paragraph = paragraphs.get((chapter_idx, para_idx))
        if not paragraph:
            if paragraph_trace is not None:
                paragraph_trace["reason"] = "paragraph_not_found"
                diagnostics.append(paragraph_trace)
            continue
        sentences = _split_sentences(str(paragraph.get("text", "")))
        if paragraph_trace is not None:
            paragraph_trace["sentence_count"] = len(sentences)
        if not sentences:
            if paragraph_trace is not None:
                paragraph_trace["reason"] = "no_sentence_spans"
                diagnostics.append(paragraph_trace)
            continue
        if len(sentences) == 1:
            # Akapit jednozdaniowy: zdanie zaczyna sie wtedy, gdy akapit, i trwa do
            # jego konca. Dopasowywanie slow nic tu nie doda, a bramka szerokosci
            # okna (>= 6 slow) odrzucala krotkie akapity - i wtedy czytnik nie mial
            # czego podswietlic. Zgloszenie: "chce, aby jednozdaniowe akapity mialy
            # kotwice".
            timestamp["sentences"] = [[
                sentences[0][0],
                sentences[0][1],
                round(float(timestamp["start_sec"]), 2),
                round(float(timestamp.get("confidence") or 0.0), 3),
            ]]
            if paragraph_trace is not None:
                paragraph_trace.update({
                    "reason": "single_sentence_fallback",
                    "stored_count": 1,
                })
                diagnostics.append(paragraph_trace)
            continue

        window_start = bisect_left(word_starts, float(timestamp["start_sec"]) - 0.01)
        window_end = min(
            len(words), bisect_right(word_starts, float(timestamp["end_sec"]) + 0.01)
        )
        if paragraph_trace is not None:
            paragraph_trace.update({
                "window_start": window_start,
                "window_end": window_end,
                "window_word_count": window_end - window_start,
            })
        if window_end - window_start < 6:
            if paragraph_trace is not None:
                paragraph_trace["reason"] = "window_lt_6"
                diagnostics.append(paragraph_trace)
            continue

        sentence_diagnostics: Optional[List[dict]] = [] if diagnostics is not None else None
        placements = _align_sentences_within(
            recognized_tokens,
            window_start,
            window_end,
            [_alignment_tokens(sentence[2]) for sentence in sentences],
            diagnostics=sentence_diagnostics,
        )
        if sentence_diagnostics is not None:
            for (char_start, char_end, _text), sentence_trace in zip(
                sentences, sentence_diagnostics
            ):
                sentence_trace["char_start"] = char_start
                sentence_trace["char_end"] = char_end
            paragraph_trace["sentence_diagnostics"] = sentence_diagnostics
            paragraph_trace["matched_placements"] = sum(
                placement is not None for placement in placements
            )

        emitted: List[list] = []
        for (char_start, char_end, _text), placement in zip(sentences, placements):
            if placement is None:
                continue
            index, score = placement
            emitted.append([
                char_start,
                char_end,
                round(float(words[index]["start"]), 2),
                round(score, 3),
            ])

        if not emitted:
            if paragraph_trace is not None:
                paragraph_trace["reason"] = "discarded_less_than_two"
                diagnostics.append(paragraph_trace)
            continue
        # Pierwsze zdanie zaczyna się wtedy, gdy akapit — nawet jeśli walk go
        # nie znalazł. Bez tego podświetlenie gaśnie na początku akapitu.
        if emitted[0][0] != sentences[0][0]:
            emitted.insert(0, [
                sentences[0][0],
                sentences[0][1],
                round(float(timestamp["start_sec"]), 2),
                round(float(timestamp.get("confidence") or 0.0), 3),
            ])
            if paragraph_trace is not None:
                paragraph_trace["forced_first_fallback"] = True
        # Akapit WIELOZDANIOWY wymaga co najmniej dwoch umieszczonych kotwic.
        #
        # Probowalem to poluzowac do jednej, zeby zwiekszyc pokrycie. Efekt byl
        # gorszy od braku: gdy dopasowanie umiesci tylko pierwsze zdanie, jedna
        # kotwica obowiazuje przez CALY akapit, wiec podswietlenie stoi na pierwszym
        # zdaniu i nie rusza sie dalej ("podswietla sie tylko pierwsze zdanie
        # akapitu, a potem pierwsze kolejnego"). Lepiej nie pokazywac nic, niz
        # wskazywac miejsce, ktorego lektor juz dawno nie czyta.
        #
        # Akapitow JEDNOZDANIOWYCH to nie dotyczy - tam jedna kotwica jest pelna
        # informacja i wychodzi wyzej, bez dopasowywania slow.
        if len(emitted) >= 2:
            timestamp["sentences"] = emitted
            final_reason = "matched"
            stored_count = len(emitted)
        else:
            final_reason = "discarded_less_than_two"
            stored_count = 0
        if paragraph_trace is not None:
            paragraph_trace.update({
                "reason": final_reason,
                "emitted_count": len(emitted),
                "stored_count": stored_count,
            })
            diagnostics.append(paragraph_trace)

    return timestamps

def _align_words_to_paragraphs(
    words: List[dict],
    epub_paragraphs: List[dict],
    audio_offset: float = 0.0,
) -> List[dict]:
    """Map recognized words to EPUB paragraphs using strong phrase anchors."""
    del audio_offset  # Zachowane dla kompatybilności wywołań.
    if not words or not epub_paragraphs:
        return []

    results = []
    total_words = len(words)
    recognized_tokens = [_alignment_tokens(str(word.get("word", ""))) for word in words]
    recognized_tokens = [tokens[0] if tokens else "" for tokens in recognized_tokens]
    paragraph_tokens = [_alignment_tokens(str(para.get("text", ""))) for para in epub_paragraphs]
    total_epub_words = sum(len(tokens) for tokens in paragraph_tokens)

    positions_by_prefix: dict[str, List[int]] = {}
    for index, token in enumerate(recognized_tokens):
        if len(token) >= 4:
            positions_by_prefix.setdefault(token[:4], []).append(index)

    min_word_idx = 0
    epub_word_offset = 0

    for para, para_words_raw in zip(epub_paragraphs, paragraph_tokens):
        expected_ratio = epub_word_offset / max(total_epub_words, 1)
        epub_word_offset += len(para_words_raw)
        anchor_tokens = [word for word in para_words_raw if len(word) >= 4][:8]
        if len(anchor_tokens) < 4:
            continue

        expected_word_idx = int(expected_ratio * total_words)
        search_radius = max(250, int(total_words * 0.18))
        search_start = max(min_word_idx, expected_word_idx - search_radius)
        search_end = min(total_words - 1, expected_word_idx + search_radius)
        candidates = positions_by_prefix.get(anchor_tokens[0][:4], [])
        candidate_slice = candidates[
            bisect_left(candidates, search_start):bisect_right(candidates, search_end)
        ]
        required_matches = max(3, math.ceil(len(anchor_tokens) * 0.7))
        best: tuple[float, float, int] | None = None

        for candidate_index in candidate_slice:
            score, matched, _cursor = _alignment_candidate_score(
                recognized_tokens, candidate_index, anchor_tokens
            )
            if matched < required_matches or score < 0.6:
                continue
            distance = abs(candidate_index - expected_word_idx) / max(total_words, 1)
            rank = score - min(distance, 1.0) * 0.05
            if best is None or rank > best[0]:
                best = (rank, score, candidate_index)

        if best is None:
            continue

        _, confidence, start_index = best
        end_idx = min(start_index + len(para_words_raw), total_words - 1)
        results.append({
            "chapter_idx": para["chapter_idx"],
            "para_idx": para["para_idx"],
            "start_sec": round(words[start_index]["start"], 2),
            "end_sec": round(words[end_idx]["end"], 2),
            "confidence": round(confidence, 3),
        })
        min_word_idx = end_idx

    return results

def _densify_paragraph_alignment(
    words: List[dict],
    epub_paragraphs: List[dict],
    timestamps: List[dict],
) -> List[dict]:
    """Fill anchor gaps by fuzzy-aligning every paragraph to cached Vosk words."""
    if not words or len(timestamps) < 2:
        return timestamps

    from rapidfuzz import fuzz

    recognized_tokens = [
        tokens[0] if tokens else ""
        for tokens in (_alignment_tokens(str(word.get("word", ""))) for word in words)
    ]
    word_starts = [float(word.get("start", 0.0)) for word in words]
    paragraphs = {
        (int(paragraph["chapter_idx"]), int(paragraph["para_idx"])): paragraph
        for paragraph in epub_paragraphs
    }
    result = list(timestamps)
    existing = {
        (int(timestamp["chapter_idx"]), int(timestamp["para_idx"]))
        for timestamp in timestamps
    }
    ordered = sorted(timestamps, key=lambda timestamp: float(timestamp["start_sec"]))

    for before, after in zip(ordered, ordered[1:]):
        chapter_idx = int(before["chapter_idx"])
        before_para = int(before["para_idx"])
        after_para = int(after["para_idx"])
        if chapter_idx != int(after["chapter_idx"]) or after_para - before_para <= 1:
            continue

        left_word = bisect_right(word_starts, float(before["start_sec"]))
        right_word = bisect_left(word_starts, float(after["start_sec"]))
        if right_word - left_word < 8:
            continue

        candidates = []
        for para_idx in range(before_para + 1, after_para):
            paragraph = paragraphs.get((chapter_idx, para_idx))
            tokens = _alignment_tokens(str(paragraph.get("text", ""))) if paragraph else []
            if len(tokens) >= 4:
                candidates.append((para_idx, tokens))
        if not candidates:
            continue

        total_tokens = sum(len(tokens) for _, tokens in candidates)
        consumed_tokens = 0
        previous_word = left_word
        word_span = right_word - left_word
        radius = max(80, min(1200, int(word_span / max(len(candidates), 1) * 2.5)))

        for para_idx, paragraph_tokens in candidates:
            midpoint = (consumed_tokens + len(paragraph_tokens) / 2) / max(total_tokens, 1)
            consumed_tokens += len(paragraph_tokens)
            expected_word = left_word + int(midpoint * word_span)
            window_start = max(previous_word, expected_word - radius)
            window_end = min(right_word, expected_word + radius)
            window_tokens = recognized_tokens[window_start:window_end]
            if len(window_tokens) < 4:
                continue

            window_text = " ".join(window_tokens)
            alignment = fuzz.partial_ratio_alignment(
                " ".join(paragraph_tokens),
                window_text,
                score_cutoff=62,
            )
            if alignment is None:
                continue

            token_char_starts = []
            cursor = 0
            for token in window_tokens:
                token_char_starts.append(cursor)
                cursor += len(token) + 1
            local_start = max(0, bisect_right(token_char_starts, alignment.dest_start) - 1)
            local_end = max(local_start, bisect_right(token_char_starts, max(alignment.dest_end - 1, 0)) - 1)
            start_index = window_start + local_start
            end_index = min(window_start + local_end, right_word - 1, len(words) - 1)
            if start_index < previous_word or end_index < start_index:
                continue

            key = (chapter_idx, para_idx)
            if key not in existing:
                result.append({
                    "chapter_idx": chapter_idx,
                    "para_idx": para_idx,
                    "start_sec": round(float(words[start_index]["start"]), 2),
                    "end_sec": round(float(words[end_index]["end"]), 2),
                    "confidence": round(float(alignment.score) / 100.0, 3),
                    "dense": True,
                })
                existing.add(key)
            previous_word = end_index + 1

    return sorted(result, key=lambda timestamp: float(timestamp["start_sec"]))
