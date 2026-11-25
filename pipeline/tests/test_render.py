import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from render import course_page


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
        self.assertIn('src="/assets/course-audit.js"', html)
        self.assertNotIn("</script>", embedded)
        self.assertEqual(audit["report"]["model"], "</script>")
        self.assertEqual(audit["coverage"][0]["unit"], "u1")
        self.assertIsNone(audit["validation"])
        self.assertNotIn("course_audit", layer)
