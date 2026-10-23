"""Fixed loopback infrastructure check; never a model/search/playback probe."""
import json
import sys
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(*, ready=False, opener=None) -> bool:
    # Ignore HTTP_PROXY/HTTPS_PROXY, and never follow a response redirect.
    target = "http://127.0.0.1:8000/health/ready" if ready else "http://127.0.0.1:8000/health"
    try:
        client = opener or build_opener(ProxyHandler({}), NoRedirect())
        with client.open(Request(target, headers={"Accept": "application/json"}), timeout=3) as response:
            if response.status != 200 or response.geturl() != target:
                return False
            payload = response.read(32_769)
        if len(payload) > 32_768:
            return False
        data = json.loads(payload)
        return isinstance(data, dict) and data.get("status") == ("ready" if ready else "ok")
    except Exception:
        return False


def main() -> int:
    if sys.argv[1:] not in ([], ["--ready"]):
        return 1
    healthy = check(ready=bool(sys.argv[1:]))
    print("healthy" if healthy else "not_ready")
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
