import json
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .model import encode

MAX_BODY = 8 * 1024 * 1024
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def check_endpoint(url: str) -> bool:
    parsed = urlsplit(url)
    local = parsed.hostname in LOOPBACK
    if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
            or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
        raise ValueError("endpoint requires HTTPS or loopback HTTP")
    return local


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(url: str, payload: dict, token: str | None = None, *, timeout=20) -> dict:
    check_endpoint(url)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, data=encode(payload).encode("utf-8"), headers=headers, method="POST")
    with build_opener(NoRedirect).open(request, timeout=timeout) as response:
        raw = response.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ValueError("response exceeds size limit")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("expected a JSON response object")
    return result
