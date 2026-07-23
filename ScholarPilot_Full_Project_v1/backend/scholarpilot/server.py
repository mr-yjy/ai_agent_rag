from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .service import SearchService


class ScholarPilotHandler(BaseHTTPRequestHandler):
    service = SearchService()
    server_version = "ScholarPilot/0.2"

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send_json({}, HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "service": "scholarpilot-python",
                    "version": "0.2.0",
                }
            )
            return
        self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path != "/api/search":
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 1_000_000:
                raise ValueError("请求体为空或过大。")
            payload = json.loads(self.rfile.read(content_length))
            query = str(payload.get("query", ""))
            mode = "live" if payload.get("mode") == "live" else "demo"
            limit = int(payload.get("limit", 10))
            result = self.service.search(query=query, mode=mode, limit=limit)
            self._send_json(result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            self._send_json(
                {"error": "服务器处理失败，请查看后端日志。"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format: str, *args: object) -> None:
        print(f"[ScholarPilot] {self.address_string()} - {format % args}")


def create_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ScholarPilotHandler)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    server = create_server(host, port)
    print(f"ScholarPilot backend: http://{host}:{server.server_port}")
    print("Health: /api/health  Search: POST /api/search")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ScholarPilot backend.")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ScholarPilot backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    run(arguments.host, arguments.port)


if __name__ == "__main__":
    main()

