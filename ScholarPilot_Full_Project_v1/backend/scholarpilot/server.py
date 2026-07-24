from __future__ import annotations

import argparse
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import __version__
from .security import (
    AuthenticationError,
    ConcurrencyLimitExceeded,
    RateLimitExceeded,
    SearchSecurity,
    SecurityConfigurationError,
    request_identity_keys,
)
from .service import LiveSearchError, SearchService


logger = logging.getLogger(__name__)


class ScholarPilotHandler(BaseHTTPRequestHandler):
    service = SearchService()
    security = SearchSecurity()
    server_version = f"ScholarPilot/{__version__}"

    def _send_json(
        self,
        payload: dict[str, Any],
        status: int = 200,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        origin = self.headers.get("Origin")
        if origin and self.security.origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin.rstrip("/"))
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, X-ScholarPilot-User",
            )
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, OPTIONS"
            )
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self.security.origin_allowed(self.headers.get("Origin")):
            self._send_json(
                {
                    "error": {
                        "code": "cors_origin_denied",
                        "message": "该 Origin 不在后端 CORS 白名单中。",
                    }
                },
                HTTPStatus.FORBIDDEN,
            )
            return
        self._send_json({}, HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "ready": self.security.proxy_token_configured,
                    "backend": {
                        "service": "scholarpilot-python",
                        "adapter": "stdlib",
                        "version": __version__,
                    },
                    "service": "scholarpilot-python",
                    "version": __version__,
                    "llm": self.service.llm_info(),
                    "academicSources": self.service.academic_sources_info(),
                    "security": self.security.status(),
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
            self.security.authorize(self.headers.get("Authorization"))
            identity_keys = request_identity_keys(
                user_id=self.headers.get("X-ScholarPilot-User"),
                forwarded_for=(
                    self.headers.get("CF-Connecting-IP")
                    or self.headers.get("X-Forwarded-For")
                    or self.headers.get("X-Real-IP")
                ),
                remote_addr=self.client_address[0],
            )
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 1_000_000:
                raise ValueError("请求体为空或过大。")
            payload = json.loads(self.rfile.read(content_length))
            query = str(payload.get("query", ""))
            mode = str(payload.get("mode", "demo"))
            if mode not in {"demo", "live"}:
                raise ValueError("mode 必须是 demo 或 live。")
            limit = int(payload.get("limit", 10))
            with self.security.admit(identity_keys):
                result = self.service.search(
                    query=query,
                    mode=mode,
                    limit=limit,
                )
            self._send_json(result)
        except SecurityConfigurationError as exc:
            self._send_json(
                {
                    "error": {
                        "code": "backend_auth_not_configured",
                        "message": str(exc),
                    }
                },
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except AuthenticationError as exc:
            self._send_json(
                {
                    "error": {
                        "code": "unauthorized",
                        "message": str(exc),
                    }
                },
                HTTPStatus.UNAUTHORIZED,
                {"WWW-Authenticate": "Bearer"},
            )
        except RateLimitExceeded as exc:
            self._send_json(
                {
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": str(exc),
                        "retryAfterSeconds": exc.retry_after_seconds,
                    }
                },
                HTTPStatus.TOO_MANY_REQUESTS,
                {"Retry-After": str(exc.retry_after_seconds)},
            )
        except ConcurrencyLimitExceeded as exc:
            self._send_json(
                {
                    "error": {
                        "code": "concurrency_limit_exceeded",
                        "message": str(exc),
                    }
                },
                HTTPStatus.TOO_MANY_REQUESTS,
                {"Retry-After": "1"},
            )
        except LiveSearchError as exc:
            self._send_json(exc.to_api(), HTTPStatus.BAD_GATEWAY)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json(
                {
                    "error": {
                        "code": "invalid_request",
                        "message": str(exc),
                    }
                },
                HTTPStatus.BAD_REQUEST,
            )
        except Exception:
            logger.exception("Unhandled POST /api/search failure")
            self._send_json(
                {"error": "服务器处理失败，请查看后端日志。"},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def log_message(self, format: str, *args: object) -> None:
        print(
            f"[ScholarPilot] {self.address_string()} - {format % args}",
            flush=True,
        )


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    service: SearchService | None = None,
    security: SearchSecurity | None = None,
) -> ThreadingHTTPServer:
    class ConfiguredScholarPilotHandler(ScholarPilotHandler):
        pass

    if service is not None:
        ConfiguredScholarPilotHandler.service = service
    if security is not None:
        ConfiguredScholarPilotHandler.security = security
    return ThreadingHTTPServer(
        (host, port),
        ConfiguredScholarPilotHandler,
    )


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    server = create_server(host, port)
    print(
        f"ScholarPilot backend: http://{host}:{server.server_port}",
        flush=True,
    )
    print("Health: /api/health  Search: POST /api/search", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ScholarPilot backend.", flush=True)
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
