from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.tutor import TutorError
from spaces import Spaces


class SpacesTest(unittest.TestCase):
    def test_nested_sources_are_stable_and_scoped(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "local.sqlite"
            spaces = Spaces(path)
            first = spaces.create("Геология")["id"]
            second = spaces.create("Геофизика")["id"]
            root = spaces.edit(first, {"action": "folder", "name": "Глава"})["entries"][0]["id"]
            child = spaces.edit(first, {"action": "folder", "name": "Примеры", "parent": root})["entries"][1]["id"]
            same_bytes = "Ракушечник сложен обломками раковин.\n<!-- page 7 -->\nПористость характеризует долю пор.".encode()
            uploaded = spaces.upload(first, "Задание.md", child, same_bytes)["added"]
            other_upload = spaces.upload(second, "Задание.md", None, same_bytes)["added"]
            self.assertNotEqual(uploaded, other_upload)
            with self.assertRaises(TutorError):
                spaces.edit(first, {"action": "move", "id": root, "parent": child})
            with self.assertRaises(TutorError):
                spaces.edit(second, {"action": "move", "id": other_upload, "parent": child})
            before = spaces.get_source(first, uploaded)
            spaces.edit(first, {"action": "rename", "id": uploaded, "name": "Наблюдения"})
            spaces.edit(first, {"action": "delete", "id": root, "contents": "keep"})

            reopened = Spaces(path)
            tree = {entry["id"]: entry for entry in reopened.view(first)["entries"]}
            self.assertIsNone(tree[child]["parent"])
            self.assertEqual(tree[uploaded]["parent"], child)
            self.assertEqual(tree[uploaded]["name"], "Наблюдения")
            self.assertEqual(reopened.get_source(first, uploaded).units, before.units)
            self.assertEqual(reopened.get_source(first, uploaded).units[-1]["page"], 7)
            self.assertEqual(reopened.original(first, uploaded)["original"], same_bytes)
            with self.assertRaises(TutorError):
                reopened.get_source(second, uploaded)
            reopened.edit(first, {"action": "delete_space"})
            self.assertEqual(reopened.list()[0]["sources"], 1)
            with self.assertRaises(TutorError):
                reopened.original(first, uploaded)

    def test_rejects_partial_import_without_leaving_entry(self):
        with TemporaryDirectory() as folder:
            spaces = Spaces(Path(folder) / "local.sqlite")
            sid = spaces.create("Геология")["id"]
            for name, data in [("пустой.txt", b" "), ("bad.docx", b"bad"), ("bad.txt", b"\xff")]:
                with self.assertRaises(TutorError):
                    spaces.upload(sid, name, None, data)
            self.assertEqual(spaces.view(sid)["entries"], [])


if __name__ == "__main__":
    unittest.main()
