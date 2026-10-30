import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from prepare_synchrobook.alignment import align_project, epub_paragraphs
from prepare_synchrobook.client import server_url
from prepare_synchrobook.core import audio_files, make_package, normalized_segment, utf16_length

FIXTURES = Path(__file__).parent / "fixtures"


def project():
    result = json.loads((FIXTURES / "project-template.json").read_text(encoding="utf-8"))
    result["epub_file"] = str((FIXTURES / "source.epub").resolve())
    return result


class PackageTests(unittest.TestCase):
    def test_package_contains_only_alignment_never_epub_or_audio(self):
        original = (FIXTURES / "source.epub").read_bytes()
        data, metadata = make_package(project())
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(archive.namelist(), ["manifest.json"])
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["text_source"], "existing-epub")
        self.assertEqual(manifest["epub_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual((FIXTURES / "source.epub").read_bytes(), original)
        self.assertEqual(len(manifest["timestamps"]), 5)
        self.assertEqual(metadata["alignment_report"]["matched_paragraphs"], 5)

    def test_true_epub_chapters_are_independent_of_audio_files(self):
        stamps, report, _ = align_project(project())
        self.assertEqual(stamps[0]["chapter_idx"], 1)  # EPUB has a title page, audio does not.
        self.assertEqual(next(stamp for stamp in stamps if stamp["chapter_idx"] == 2)["start_sec"], 62)
        self.assertEqual(report["total_paragraphs"], 7)
        self.assertEqual(len(report["unmatched"]), 2)
        self.assertTrue(all(not stamp["interpolated"] for stamp in stamps))

    def test_utf16_offsets_match_javascript_and_original_punctuation(self):
        stamps, _, _ = align_project(project())
        paragraphs, _ = epub_paragraphs(FIXTURES / "source.epub")
        text = next(p["text"] for p in paragraphs if p["chapter_idx"] == 1)
        self.assertEqual(stamps[0]["sentences"][0][1], len(text) + 1)
        self.assertEqual(utf16_length("ą🌙"), 3)

    def test_wrong_epub_hash_is_refused_without_modifying_it(self):
        draft = project()
        draft["epub_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "różni"):
            make_package(draft)

    def test_unrelated_audio_cannot_create_fictional_anchors(self):
        draft = project()
        for chapter in draft["chapters"]:
            for segment in chapter["segments"]:
                for word in segment["words"]:
                    word["word"] = "zupełnieinne"
        with self.assertRaisesRegex(ValueError, "wiarygodnych"):
            make_package(draft)

    def test_missing_epub_or_missing_recognized_words_requires_input(self):
        draft = project()
        draft.pop("epub_file")
        with self.assertRaisesRegex(ValueError, "EPUB"):
            make_package(draft)
        draft = project()
        for chapter in draft["chapters"]:
            chapter["segments"] = []
        with self.assertRaisesRegex(ValueError, "słów"):
            make_package(draft)

    def test_silence_advances_full_file_timeline(self):
        draft = project()
        draft["chapters"][0]["source"]["duration_sec"] += 120
        stamps, _, _ = align_project(draft)
        self.assertEqual(next(stamp for stamp in stamps if stamp["chapter_idx"] == 2)["start_sec"], 182)

    def test_invalid_recognized_word_time_is_rejected(self):
        for start, end in [(float("nan"), 2), (-1, 2), (5, 4), (1, 100)]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                normalized_segment({"text": "tekst", "start": 1, "end": 10,
                                    "words": [{"word": "tekst", "start": start, "end": end}]}, 60)

    def test_natural_order_excludes_other_files_and_directories(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for filename in ["10.mp3", "2.mp3", "1.mp3", "metadata.json"]:
                (root / filename).write_bytes(b"x")
            (root / "folder.mp3").mkdir()
            self.assertEqual([p.name for p in audio_files(root)], ["1.mp3", "2.mp3", "10.mp3"])

    def test_secure_server_addresses(self):
        for value in ["https://nokturn-library.pl/", "http://192.168.50.75:8000", "http://127.0.0.1:4180"]:
            self.assertEqual(server_url(value), value.rstrip("/"))
        for value in ["http://example.com", "https://user:secret@example.com", "file:///tmp/a", "https://example.com?token=secret"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server_url(value)


if __name__ == "__main__":
    unittest.main()
