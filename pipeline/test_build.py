import unittest
from copy import deepcopy
from build import units_for, excerpt_node, validate


class PipelineTest(unittest.TestCase):
    def setUp(self):
        page={"pdf_page":3,"ocr":"Мощность пласта в этом примере составляет 12 м.\n\n----\n━━━ FORMAT TEST\nДогадка OCR.\n----\n\nВторой абзац."}
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

if __name__=="__main__":
    unittest.main()
