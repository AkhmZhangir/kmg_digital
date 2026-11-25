from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from core.tutor import TutorError
from spaces import DOCUMENTS_ID, Spaces, extract_units


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

    def test_unfiled_document_moves_between_libraries_with_its_id_and_original(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "local.sqlite"
            spaces = Spaces(path)
            library = spaces.create("Геология")["id"]
            root = spaces.edit(library, {"action": "folder", "name": "Глава"})["entries"][0]["id"]
            data = "Пористость характеризует долю пор.".encode()
            entry = spaces.upload(DOCUMENTS_ID, "Книга.txt", None, data)["added"]
            self.assertEqual([item["id"] for item in spaces.list()], [library])
            self.assertEqual(spaces.documents()["sources"], 1)
            with self.assertRaises(TutorError):
                spaces.edit(DOCUMENTS_ID, {"action": "delete_space"})
            with self.assertRaises(TutorError):
                spaces.edit(DOCUMENTS_ID, {"action": "move", "id": entry, "destination": library, "parent": entry})
            self.assertEqual(spaces.documents()["sources"], 1)

            spaces.edit(DOCUMENTS_ID, {"action": "move", "id": entry, "destination": library, "parent": root})
            spaces = Spaces(path)
            self.assertEqual(spaces.view(DOCUMENTS_ID)["entries"], [])
            self.assertEqual(spaces.list()[0]["sources"], 1)
            self.assertEqual(spaces.view(library)["entries"][1]["parent"], root)
            self.assertEqual(spaces.original(library, entry)["original"], data)
            self.assertEqual(spaces.get_source(library, entry).units[0]["id"], entry + ".u001")
            spaces.edit(library, {"action": "move", "id": entry, "destination": DOCUMENTS_ID})
            self.assertEqual(spaces.documents()["sources"], 1)

    def test_library_can_index_pdf_above_legacy_page_limit(self):
        pages = [SimpleNamespace(extract_text=lambda: "Проницаемость горной породы. " * 4)] * 101
        with patch("pypdf.PdfReader", return_value=SimpleNamespace(pages=pages)):
            units = extract_units("book", ".pdf", b"pdf fixture")
        self.assertEqual({unit["page"] for unit in units}, set(range(1, 102)))

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
