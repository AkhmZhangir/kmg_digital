import unittest
from types import SimpleNamespace

from assessments import generate, search_sources
from core.tutor import Source, TutorError


class AssessmentsTest(unittest.TestCase):
    def setUp(self):
        self.quote = "Пористость определяют как долю порового объёма в полном объёме породы."
        self.source = Source("rocks", "Геология", [{"id": "u1", "page": 9, "text": self.quote}])
        self.lib = SimpleNamespace(get=lambda _: self.source)
        self.task = {"ref": 1, "quote": self.quote, "question": "Что характеризует пористость?",
                     "options": ["Долю пор", "Размер зерна", "Массу породы"], "answer": 0,
                     "explanation": "Это доля объёма пор."}

    def test_model_questions_require_valid_citations_and_answers(self):
        invalid = [dict(self.task, ref=3), dict(self.task, answer=True),
                   dict(self.task, quote="Кварц относится к сульфидам и имеет металлический блеск.")]
        model = SimpleNamespace(is_mock=False, name="fixture", chat_json=lambda *args, **kw: {"tasks": invalid + [self.task]})
        response = generate(self.lib, model, {"mode": "practice", "sources": ["rocks"]})
        self.assertEqual(len(response["tasks"]), 1)
        self.assertEqual(response["tasks"][0]["citation"]["page"], 9)
        with self.assertRaises(TutorError):
            generate(self.lib, model, {"mode": "exam", "sources": ["rocks"]})

    def test_search_link_points_to_matching_step(self):
        from pathlib import Path
        layer = {"chapter": {"title_short": "Петрофизика"},
                 "nodes": [{"id": "step1", "units": ["u1"]}], "glossary": []}
        self.source = Source("rocks", "Геология", self.source.units, layer, Path("test_chapter"))
        self.lib.list = lambda: [{"kind": "chapter", "id": "rocks"}]
        hit, = search_sources(self.lib, "пористостью")
        self.assertEqual((hit["folder"], hit["node"], hit["page"]), ("test_chapter", "step1", 9))


if __name__ == "__main__":
    unittest.main()
