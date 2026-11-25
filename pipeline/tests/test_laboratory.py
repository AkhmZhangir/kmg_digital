import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from laboratory import HERE, activity, candidates, catalogue, evaluate, registry
from core.llm import LLM
from core.tutor import Library
from server import make_handler


class LabTest(unittest.TestCase):
    node = {"id": "n", "title": "Обсидиан", "claims": []}

    def test_library(self):
        for a in registry():
            self.assertTrue((HERE / a["media_url"]).read_bytes().startswith(b"\xff\xd8"))
            self.assertTrue(a["reference"].startswith("https://"))
        self.assertEqual(len(registry()), 7)
        thin, = [a for a in catalogue() if a.get("views")]
        self.assertNotIn("answers", thin)
        self.assertEqual(set(thin["views"]), {"ppl", "xpl"})
        self.assertEqual(candidates("pyrite")[0]["asset_id"], "mineral_01")
        self.assertFalse(candidates("пирит", media_type="model"))

    def test_validated_selection(self):
        model = Mock(is_mock=False)
        model.chat_json.return_value = {"action": "open_virtual_lab", "asset_id": "https://example.net", "instructions": "bad"}
        task = activity(model, self.node, {})
        self.assertEqual(task["asset_id"], "rock_02")
        self.assertNotIn("answers", task)
        model.chat_json.return_value = {"action": "open_virtual_lab", "asset_id": "rock_02", "instructions": "Осмотри скол."}
        self.assertEqual(activity(model, self.node, {})["guidance"], "ИИ-тьютор")
        model.reset_mock()
        self.assertEqual(activity(model, {"title": "Алгебра"}, {})["action"], "study_text")
        model.chat_json.assert_not_called()

    def test_open_answers(self):
        model = Mock(is_mock=False)
        data = dict(asset_id="rock_02", choice="Другая гипотеза", observation="Возможно, это стекло с раковистым изломом.")
        model.chat_json.return_value = {"status": "correct", "feedback": "Гипотеза подкреплена наблюдением.", "followup": "Как её проверить?"}
        self.assertEqual(evaluate(model, self.node, data)["status"], "correct")
        model.chat_json.side_effect = TimeoutError()
        self.assertEqual(evaluate(model, self.node, data)["status"], "uncertain")
        self.assertEqual(evaluate(model, self.node, dict(data, choice="Базальт"))["status"], "retry")
        with self.assertRaises(ValueError):
            evaluate(model, self.node, dict(data, asset_id="mineral_01"))

    def test_upload_through_tutor(self):
        with TemporaryDirectory() as folder:
            lib = Library(Path(folder))
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(lib, LLM("mock"), Path(folder)))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            def post(path, data):
                with urlopen(Request(base + "/api/" + path, data=json.dumps(data).encode(),
                                     headers={"Content-Type": "application/json"})) as response:
                    return json.load(response)
            try:
                with urlopen(base + "/api/lab/catalogue") as catalog:
                    slide = next(a for a in json.load(catalog)["assets"] if a.get("views"))
                pair = []
                for url in slide["views"].values():
                    with urlopen(base + url) as photo:
                        self.assertEqual(photo.headers.get_content_type(), "image/jpeg")
                        pair.append(photo.read())
                self.assertNotEqual(*pair)
                reply = post("lab/observation", {"asset_id": slide["asset_id"], "question": "Что наблюдать?"})
                self.assertEqual(reply["by"], "Подсказка из каталога")

                src = post("sources", {"name": "rock.md", "text": "Ракушечник содержит фрагменты раковин."})
                data = {"source": src["id"], "node": None}
                reply = post("chat", {"sources": [src["id"]], "mode": "practice", "message": "Что содержит ракушечник?"})
                self.assertEqual(reply["action"]["source"], src["id"])
                self.assertTrue(post("lab/recommend", data)["available"])
                task = post("lab/open", data)
                self.assertEqual(task["asset_id"], "rock_01")
                with urlopen(base + task["media_url"]) as image:
                    self.assertTrue(image.read().startswith(b"\xff\xd8"))
                data.update(asset_id=task["asset_id"], choice="Ракушечник", observation="Обломки раковин")
                self.assertEqual(post("lab/grade", data)["status"], "correct")
                self.assertIn("реестра", post("lab/hint", dict(data, question="Куда смотреть?"))["by"])
                with self.assertRaises(HTTPError) as failure:
                    post("lab/open", dict(source="unknown"))
                failure.exception.close()
            finally:
                server.shutdown()
                thread.join()
                server.server_close()
