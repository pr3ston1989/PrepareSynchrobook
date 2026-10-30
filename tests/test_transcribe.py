import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from prepare_synchrobook.core import Cancelled

EPUB_FILE = Path(__file__).parent / "fixtures" / "source.epub"
from prepare_synchrobook.transcribe import prepare


class TranscribeTests(unittest.TestCase):
    def fingerprint(self, path, cancel):
        data = path.read_bytes()
        return {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "duration_sec": 20.0}

    def test_cancelled_second_file_resumes_first_file_from_cache(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            audio, output = root / "audio", root / "output"
            audio.mkdir()
            for filename in ["01.mp3", "02.mp3"]:
                (audio / filename).write_bytes(filename.encode())
            calls = []
            class Model:
                def transcribe(self, path, **kwargs):
                    calls.append(Path(path).name)
                    segment = SimpleNamespace(text="Żółw słucha opowieści.", start=2.0, end=8.0, no_speech_prob=.1, avg_logprob=-.2, words=[SimpleNamespace(word="Żółw",start=2.0,end=3.0)])
                    return iter([segment]), None
            cancelled = [False]
            def notify(text):
                if text.startswith("1/2"):
                    cancelled[0] = True
            with patch("prepare_synchrobook.transcribe.fingerprint", self.fingerprint):
                with self.assertRaises(Cancelled):
                    prepare(audio, output, "Tytuł", "Autor", notify=notify, cancel=lambda: cancelled[0], model_factory=lambda *args, **kwargs: Model(), epub_file=EPUB_FILE)
                self.assertEqual(calls, ["01.mp3"])
                self.assertTrue((output / "draft.json").exists())
                calls.clear()
                result = prepare(audio, output, "Tytuł", "Autor", model_factory=lambda *args, **kwargs: Model(), epub_file=EPUB_FILE)
                self.assertEqual(calls, ["02.mp3"])
                self.assertEqual(len(result["chapters"]), 2)
                # Content change invalidates only that file; model change invalidates both.
                calls.clear()
                (audio / "01.mp3").write_bytes(b"different-recording")
                prepare(audio, output, "Tytuł", "Autor", model_factory=lambda *args, **kwargs: Model(), epub_file=EPUB_FILE)
                self.assertEqual(calls, ["01.mp3"])
                calls.clear()
                prepare(audio, output, "Tytuł", "Autor", model_name="base", model_factory=lambda *args, **kwargs: Model(), epub_file=EPUB_FILE)
                self.assertEqual(calls, ["01.mp3", "02.mp3"])

    def test_no_speech_rejection_does_not_create_fake_text(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            audio, output = root / "audio", root / "output"
            audio.mkdir()
            (audio / "01.mp3").write_bytes(b"silence")
            class Model:
                def transcribe(self, *args, **kwargs):
                    segment = SimpleNamespace(text="Dziękuję za oglądanie", start=1.0, end=2.0, no_speech_prob=.99, avg_logprob=-2)
                    return iter([segment]), None
            with patch("prepare_synchrobook.transcribe.fingerprint", self.fingerprint):
                result = prepare(audio, output, "Cisza", "QA", model_factory=lambda *args, **kwargs: Model(), epub_file=EPUB_FILE)
            self.assertEqual(result["chapters"][0]["segments"], [])
