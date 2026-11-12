import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

from .application import Principal
from .http import MAX_BODY, post_json
from .model import encode

SCOPES = frozenset({"write", "decide", "approve", "observe", "promote"})


class Authenticator:
    def __init__(self, credentials: dict):
        if not isinstance(credentials, dict) or not credentials:
            raise ValueError("at least one service credential is required")
        self.entries = {}
        for token, config in credentials.items():
            if not isinstance(token, str) or not token or not token.isascii() or token.strip() != token:
                raise ValueError("invalid token configuration")
            groups = config.get("groups", [])
            scopes = config.get("scopes", [])
            if not isinstance(groups, list) or not all(isinstance(group, str) and group for group in groups):
                raise ValueError("invalid token groups")
            if not isinstance(scopes, list) or not set(scopes) <= SCOPES:
                raise ValueError("invalid token scopes")
            self.entries[token.encode()] = Principal(frozenset(groups), frozenset(scopes))

    def authenticate(self, token: str) -> Principal | None:
        encoded = token.encode("utf-8")
        found = None
        for expected, principal in self.entries.items():
            if hmac.compare_digest(expected, encoded):
                found = principal
        return found


class Remote:
    def __init__(self, base: str, token: str):
        if not token:
            raise ValueError("SAGEKIT_TOKEN is required for remote use")
        self.base = base.rstrip("/")
        self.token = token

    def dispatch(self, operation, params):
        return post_json(f"{self.base}/v1/{operation}", params, self.token)["result"]


def service(application, credentials, host="127.0.0.1", port=8765):
    auth = Authenticator(credentials)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(20)
            super().setup()

        def log_message(self, *args):
            # Request URLs and headers are outside the decision audit envelope.
            pass

        def reply(self, status, data):
            payload = encode(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            scheme, _, token = self.headers.get("Authorization", "").partition(" ")
            principal = auth.authenticate(token) if scheme.lower() == "bearer" else None
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    raise ValueError("invalid request size")
                body = self.rfile.read(length)
            except (ValueError, OSError):
                if principal is None:
                    self.reply(401, {"error": "authentication required"})
                else:
                    self.reply(400, {"error": "invalid request size"})
                return
            # Drain the bounded POST body before closing rejected connections.
            # Windows can reset the connection if unread request bytes remain.
            if principal is None:
                self.reply(401, {"error": "authentication required"})
                return
            if not self.path.startswith("/v1/") or "/" in self.path[4:]:
                self.reply(404, {"error": "unknown operation"})
                return
            try:
                if len(body) != length:
                    raise ValueError("incomplete request body")
                data = json.loads(body)
                if not isinstance(data, dict):
                    raise ValueError("expected a JSON object")
                result = application.dispatch(self.path[4:], data, principal)
            except PermissionError:
                self.reply(403, {"error": "insufficient permission"})
            except KeyError:
                self.reply(400, {"error": "invalid request fields"})
            except LookupError:
                self.reply(404, {"error": "unknown operation"})
            except (ValueError, TypeError, AttributeError, OverflowError):
                self.reply(400, {"error": "invalid request"})
            except Exception:
                self.reply(500, {"error": "operation failed"})
            else:
                self.reply(200, {"result": result})

    return ThreadingHTTPServer((host, port), Handler)
