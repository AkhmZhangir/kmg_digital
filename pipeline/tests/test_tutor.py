import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.tutor import Library, TutorError, chat  # noqa: E402


class FakeLLM:
    name, is_mock = "fake", False

    def __init__(self, answer):
        self.answer = answer

    def chat_json(self, system, payload, temperature=0.2, task=""):
        self.payload = payload
        return self.answer(payload) if callable(self.answer) else self.answer


UNITS = [
    {"id": "u1", "page": 10, "kind": "para", "text": "Пористость коллектора определяют по данным акустического каротажа и плотностного каротажа."},
    {"id": "u2", "page": 11, "kind": "para", "text": "Глинистость снижает проницаемость и искажает показания нейтронного метода."},
]


class TutorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name) / "train_x"
        d.mkdir()
        layer = {"chapter": {"id": "x", "book": "Книга"}, "nodes": [{"id": "x.n1", "title": "Пористость", "units": ["u1"], "summary": []}]}
        (d / "layer.json").write_text(json.dumps(layer, ensure_ascii=False), encoding="utf-8")
        (d / "units.json").write_text(json.dumps(UNITS, ensure_ascii=False), encoding="utf-8")
        self.lib = Library(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_citations_verified_and_fake_dropped(self):
        def ans(p):
            ref = p["context"][0]["id"]
            return {"answer": "Ок", "citations": [{"ref": ref, "quote": "определяют по данным акустического каротажа"},
                                                   {"ref": ref, "quote": "этого текста в книге точно нет совсем"}]}
        res = chat(self.lib, FakeLLM(ans), {"message": "как определить пористость?", "sources": ["x"], "lesson": "x.n1"})
        self.assertEqual(len(res["citations"]), 1)
        self.assertEqual(res["citations"][0]["page"], 10)
        self.assertEqual(res["dropped_citations"], 1)
        self.assertFalse(res["unverified"])

    def test_folder_alias_and_errors(self):
        self.assertIs(self.lib.get("train_x"), self.lib.get("x"))
        with self.assertRaises(TutorError):
            chat(self.lib, FakeLLM({}), {"message": "", "sources": ["x"]})
        with self.assertRaises(TutorError):
            chat(self.lib, FakeLLM({}), {"message": "вопрос", "sources": ["nope"]})

    def test_upload_text_source(self):
        src = self.lib.add_text("notes.md", "<!-- page 5 -->\nПесчаник с высокой пористостью — хороший коллектор нефти.\n\nКоротко")
        self.assertEqual(src.units[0]["page"], 5)
        self.assertEqual(len(src.units), 1)

    def test_upload_long_txt_not_truncated(self):
        # Обычный TXT без пустых строк: раньше становился одним куском и обрезался до 3000 знаков.
        lines = [f"Строка {i}: пласт номер {i} описан как песчаник средней плотности." for i in range(1, 150)]
        lines.append("Важно: в пласте номер 150 получен приток нефти 42 тонны в сутки.")
        src = self.lib.add_text("big.txt", "\n".join(lines))
        self.assertGreater(len(src.units), 3)
        self.assertTrue(all(len(u["text"]) <= 1200 for u in src.units))
        self.assertIn("42 тонны", src.units[-1]["text"])

    def test_upload_page_markers_inline(self):
        src = self.lib.add_text("p.md", "Шапка файла\n<!-- page 1 -->\nСкважина 17: сужение ствола в коллекторе.\n<!-- page 2 -->\nНиже плотные известняки, не коллектор.")
        self.assertEqual([u["page"] for u in src.units if "известняки" in u["text"]], [2])
        self.assertEqual(src.meta()["pages"], [1, 2])


if __name__ == "__main__":
    unittest.main()
