"""Тесты ядра: py -3 -m unittest discover -s tests (из каталога pipeline)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.llm import extract_json  # noqa: E402
from core.textnorm import looks_garbled, numbers, quote_match  # noqa: E402
from core.units import chapter_pages, split_units  # noqa: E402
from core.verify import check_claim, check_task  # noqa: E402

SRC = ("Коллекторами  считают пласты, в которых $k_{п,эф} > 1\\%$, учитывая, что значения $k_{п,эф} < 1\\%$ "
       "могут соответствовать отклонениям кривых U, обусловленным аппаратурными помехами.")


class TextNorm(unittest.TestCase):
    def test_quote_exact_despite_spacing_and_latex(self):
        self.assertEqual(quote_match("Коллекторами считают пласты, в которых k_{п,эф} > 1%", SRC)[0], "exact")

    def test_quote_rejects_invented(self):
        self.assertEqual(quote_match("Коллекторами считают пласты с пористостью выше 20 процентов", SRC)[0], "none")

    def test_numbers(self):
        self.assertEqual(numbers("1,50 м и 2.5 и 1"), {"1.5", "2.5", "1"})

    def test_garbled(self):
        self.assertTrue(looks_garbled("101. OchoBbAcb Ha pe3yIbTaTax peHHeHH npeIbIyIeH 3aJaH, BbUHcJIHTb, KaKa OIIb6a B OIIpeJIeHHN"))
        self.assertFalse(looks_garbled(SRC))


class Units(unittest.TestCase):
    def test_trim_and_split(self):
        pages = {1: "хвост прошлой главы\n\n# Глава V\n\nПервый абзац продолжается", 2: "на следующей странице.\n\n# § 21. Дальше"}
        ch = chapter_pages(pages, [{"from": 1, "to": 2, "start": "^# Глава V", "end": "^# § 21"}])
        units = split_units(ch)
        self.assertEqual([u.kind for u in units], ["heading", "para"])
        self.assertEqual(units[1].pages, [1, 2])
        self.assertIn("на следующей странице", units[1].text)


class Verify(unittest.TestCase):
    units = {"u1": {"id": "u1", "page": 90, "kind": "para", "text": SRC}}

    def test_claim(self):
        ok, _ = check_claim({"unit": "u1", "quote": "могут соответствовать отклонениям кривых U"}, self.units)
        self.assertTrue(ok)
        ok, _ = check_claim({"unit": "u1", "quote": "нефть всегда даёт высокое сопротивление пласта"}, self.units)
        self.assertFalse(ok)

    def test_tasks(self):
        text = SRC
        self.assertIsNone(check_task({"type": "single", "question": "?", "options": ["a", "b"], "answer": 1}, text))
        self.assertIsNotNone(check_task({"type": "single", "question": "?", "options": ["a", "a"], "answer": 0}, text))
        self.assertIsNone(check_task({"type": "cloze", "question": "?", "text": "считают {{1}}", "answers": [["пласты"]]}, text))
        self.assertIsNotNone(check_task({"type": "cloze", "question": "?", "text": "{{1}}", "answers": [["динозавры"]]}, text))
        self.assertIsNotNone(check_task({"type": "calc", "question": "Пласт 77 м", "answer": 3}, text))


class Json(unittest.TestCase):
    def test_latex_escapes(self):
        bs = chr(92)
        raw = '{"f": "' + bs + 'frac{a} ' + bs + 'times ' + bs + 'rho ' + bs + '(x' + bs + ')", "n": "a' + bs + 'nб"}'
        want = bs + "frac{a} " + bs + "times " + bs + "rho " + bs + "(x" + bs + ")"
        self.assertEqual(extract_json(raw), {"f": want, "n": "a\nб"})

    def test_extract(self):
        self.assertEqual(extract_json('<think>хм {"x":1}</think>Ответ:\n```json\n{"a": "}"}\n```'), {"a": "}"})


if __name__ == "__main__":
    unittest.main()
