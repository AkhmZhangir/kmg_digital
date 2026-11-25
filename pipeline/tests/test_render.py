import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from render import OFFICIAL_FILES, course_page, read_course_audit


class CoursePageTest(unittest.TestCase):
    def test_report_is_embedded_without_changing_layer_or_breaking_the_script(self):
        layer = {"chapter": {"title": "Геология"}, "nodes": []}
        with TemporaryDirectory() as out:
            path = Path(out)
            (path / "report.json").write_text('{"model": "</script>", "claims_verified_share": 0.8}', encoding="utf-8")
            (path / "coverage.json").write_text('[{"unit": "u1", "node": null}]', encoding="utf-8")
            html = course_page(layer, path, assets="/assets/")
        embedded = re.search(r'id="layer">(.+?)</script>', html).group(1)
        audit = json.loads(embedded)["course_audit"]
        self.assertIn('src="/assets/course-audit.js', html)
        self.assertNotIn("</script>", embedded)
        self.assertEqual(audit["report"]["model"], "</script>")
        self.assertEqual(audit["coverage"][0]["unit"], "u1")
        self.assertIsNone(audit["validation"])
        self.assertNotIn("course_audit", layer)

    def test_empty_glossary_uses_only_reference_terms_mentioned_in_the_chapter(self):
        layer = {"chapter": {}, "nodes": [{"id": "n1", "claims": [
            {"page": 12, "quote": "Гистограмма пористости коллекторов."}],
            "summary": [{"page": 13, "text": "Комплекс ГИС."}]}], "glossary": []}

        def entries():
            html = course_page(layer)
            return json.loads(re.search(r'id="layer">(.+?)</script>', html).group(1))["glossary"]

        by_term = {row["term"]: row for row in entries()}
        self.assertEqual(set(by_term), {"пористость", "коллектор", "ГИС"})
        self.assertEqual(by_term["ГИС"]["page"], 13)
        self.assertEqual(by_term["пористость"]["node_id"], "n1")
        self.assertTrue(all(row["reference"] for row in by_term.values()))
        self.assertEqual(layer["glossary"], [])
        layer["glossary"] = [{"term": "Авторский термин"}]
        self.assertEqual(entries(), layer["glossary"])

    def test_quality_requires_all_schema_checks_and_at_least_80_percent_citations(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)
            self.assertFalse(read_course_audit(path)["needs_review"])
            official = path / "official"
            official.mkdir()
            checks = {name: {"ok": True} for name in OFFICIAL_FILES}
            report = path / "report.json"
            validation = official / "validation.json"
            validation.write_text(json.dumps(checks), encoding="utf-8")
            report.write_text('{"claims_verified_share": 0.8}', encoding="utf-8")
            self.assertFalse(read_course_audit(path)["needs_review"])
            report.write_text('{"claims_verified_share": 0.79}', encoding="utf-8")
            self.assertTrue(read_course_audit(path)["needs_review"])
            report.write_text('{"claims_verified_share": 0.99}', encoding="utf-8")
            checks["layer.json"]["ok"] = False
            validation.write_text(json.dumps(checks), encoding="utf-8")
            self.assertTrue(read_course_audit(path)["needs_review"])
