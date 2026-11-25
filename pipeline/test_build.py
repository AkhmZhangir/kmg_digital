import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from build import units_for, excerpt_node, generate_node, validate
from prepare import load_source


class PipelineTest(unittest.TestCase):
    def setUp(self):
        page={"pdf_page":3,"ocr":"Мощность пласта в этом примере составляет 12 м по данным скважинных измерений.\n\n----\n━━━ FORMAT TEST\nДогадка OCR.\n----\n\nВторой абзац."}
        units=units_for(page,"sample")
        self.assertEqual([u["kind"] for u in units],["текст","описание иллюстрации OCR","текст"])
        self.units=[units[0],units[2]]
        self.node=excerpt_node(self.units,3)

    def test_grounding(self):
        validate(self.node,self.units)
        for field,value in [("text","Получено 21 м"),("quote","Придуманная цитата")]:
            node=deepcopy(self.node)
            node["claims"][0][field]=value
            with self.assertRaises(ValueError):
                validate(node,self.units)

    def test_model_can_correct_an_invalid_citation(self):
        incorrect = deepcopy(self.node)
        incorrect["claims"][0]["quote"] = "Цитата отсутствует"
        usage = []
        with patch("build.model_node", side_effect=[(incorrect, {"calls": 1}), (self.node, {"calls": 1})]) as call:
            self.assertEqual(generate_node(self.units, None, [], usage), self.node)
        self.assertIn("Цитата отсутствует", call.call_args.args[-1])
        self.assertEqual(len(usage), 2)

    def test_marked_and_unmarked_sources_keep_distinct_references(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "chapter.md"
            path.write_text("Текст без разметки.", encoding="utf-8")
            pages, label = load_source(path)
            self.assertEqual((list(pages), label), ([1], "Блок источника"))
            path.write_text("<!-- page 7 -->\nТекст страницы.\n<!-- page 9 -->\nДругая страница.", encoding="utf-8")
            pages, label = load_source(path, "7,9")
            self.assertEqual((list(pages), label), ([7, 9], "PDF-стр."))
            with self.assertRaises(ValueError):
                load_source(path, "7-9")


if __name__=="__main__":
    unittest.main()
