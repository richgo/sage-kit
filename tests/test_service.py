from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError

from sagekit.application import Application
from sagekit.http import post_json
from sagekit.repository import LocalRepository
from sagekit.service import service

from test_foundation import record


class ServiceTests(unittest.TestCase):
    def test_authenticated_cli_use_cases_and_acl(self):
        with tempfile.TemporaryDirectory() as root:
            app = Application(LocalRepository(Path(root)))
            with service(app, {"reader": {"groups": []},
                               "writer": {"groups": ["sre"], "scopes": ["write"]}},
                         port=0) as server:
                thread = Thread(target=server.serve_forever)
                thread.start()
                try:
                    url = f"http://127.0.0.1:{server.server_port}/v1/"
                    secret = record(acl=("sre",)).as_dict()
                    with self.assertRaises(HTTPError) as error:
                        post_json(url + "list", {})
                    self.assertEqual(401, error.exception.code)
                    with self.assertRaises(HTTPError) as error:
                        post_json(url + "add", {"record": secret}, "reader")
                    self.assertEqual(403, error.exception.code)
                    post_json(url + "add", {"record": secret}, "writer")
                    self.assertEqual([secret], post_json(url + "list", {}, "writer")["result"])
                    self.assertEqual([], post_json(url + "list", {}, "reader")["result"])
                    with self.assertRaises(HTTPError) as error:
                        post_json(url + "list", {"groups": ["sre"]}, "reader")
                    self.assertEqual(400, error.exception.code)
                finally:
                    server.shutdown()
                    thread.join()

    def test_public_export_has_no_private_text_and_escapes_html(self):
        with tempfile.TemporaryDirectory() as root:
            app = Application(LocalRepository(Path(root) / "corpus"))
            app.repo.append(record("<script>"))
            app.repo.append(record("secret", acl=("private",)))
            output = Path(root) / "site"
            app.export_public(output)
            page = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("&lt;script&gt;", page)
            self.assertNotIn("secret", page)
