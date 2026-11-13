from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest

from sagekit.decisions import DecisionRequest, ProviderUnavailable
from sagekit.providers import JevProvider


class JevWireContract(unittest.TestCase):
    def test_batches_nouls_and_choice_with_the_same_state_and_evidence(self):
        calls = []

        class Provider(JevProvider):
            def call(self, payload):
                calls.append(payload)
                return {"model": "fixture", "answers": {
                    "coverage": {"type": "noul", "noul": .95},
                    "isolation": {"type": "noul", "noul": .9},
                    "action": {"type": "choice", "choice": "pass", "confidence": .8,
                               "probabilities": {"pass": .9, "hold": .1}},
                }}

        provider = Provider("http://127.0.0.1:1/v1/systemone", None)
        state = {"service": "checkout"}
        answers = provider.decide_many({
            "coverage": (DecisionRequest("noul", "Are the tests sufficient?", state), []),
            "isolation": (DecisionRequest("noul", "Is the run isolated?", state), []),
            "action": (DecisionRequest("choice", "Choose an action", state,
                                       {"pass": "Proceed", "hold": "Review"}), []),
        })
        self.assertEqual(1, len(calls))
        self.assertEqual({"coverage", "isolation", "action"}, set(calls[0]["questions"]))
        self.assertEqual("pass", answers["action"]["value"])
        self.assertEqual(.95, answers["coverage"]["value"])

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
