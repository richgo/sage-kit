from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest

from sagekit.decisions import DecisionRequest, ProviderUnavailable
from sagekit.providers import JevProvider


class JevWireContract(unittest.TestCase):
    def test_local_jev_compatible_endpoint_and_invalid_response(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append((self.path, data))
                answer = .95 if len(requests) == 1 else 2.0
                payload = json.dumps({"model": "fixture", "answers": {
                    "sagekit": {"type": "noul", "noul": answer}}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            try:
                provider = JevProvider(f"http://127.0.0.1:{server.server_port}/v1/systemone", None)
                request = DecisionRequest("noul", "Do the tests cover retries?", "Checkout retries")
                result = provider.decide(request, [])
                self.assertEqual("jev-oss", result["provider"])
                self.assertEqual(.95, result["value"])
                self.assertEqual("/v1/systemone", requests[0][0])
                self.assertEqual({"type": "noul", "instructions": request.instructions},
                                 requests[0][1]["questions"]["sagekit"])
                with self.assertRaises(ProviderUnavailable):
                    provider.decide(request, [])
            finally:
                server.shutdown()
                worker.join()
