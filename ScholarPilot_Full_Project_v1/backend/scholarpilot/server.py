from __future__ import annotations

import argparse
import inspect
import json
import logging
import time
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
from .service import (
    LiveSearchError,
    SearchService,
    api_error,
    new_request_id,
)


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
                "Content-Type, Authorization, X-ScholarPilot-User, "
                "X-ScholarPilot-LLM-Key, X-ScholarPilot-LLM-Model",
            )
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, OPTIONS"
            )
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("Client disconnected before response delivery")

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
                    "schemaVersion": "1.0",
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
        request_id = new_request_id(self.headers.get("X-Request-ID"))
        self._send_json(
            api_error(
                code="not_found",
                message="Not found",
                request_id=request_id,
            ),
            HTTPStatus.NOT_FOUND,
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        request_id = new_request_id(self.headers.get("X-Request-ID"))
        if path != "/api/search":
            self._send_json(
                api_error(
                    code="not_found",
                    message="Not found",
                    request_id=request_id,
                ),
                HTTPStatus.NOT_FOUND,
            )
            return

        admitted_started = time.perf_counter()
        try:
            self.security.authorize(self.headers.get("Authorization"))
            user_llm_key = self.headers.get("X-ScholarPilot-LLM-Key")
            if not user_llm_key:
                self._send_json(
                    api_error(
                        code="llm_api_key_required",
                        message=(
                            "请先在网页设置中添加你的 "
                            "DeepSeek API Key。"
                        ),
                        request_id=request_id,
                    ),
                    HTTPStatus.BAD_REQUEST,
                )
                return
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
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象。")
            unexpected_fields = set(payload) - {"query", "limit"}
            if unexpected_fields:
                raise ValueError(
                    "请求包含不支持的字段："
                    + ", ".join(sorted(unexpected_fields))
                    + "。"
                )
            query = str(payload.get("query", ""))
            limit = int(payload.get("limit", 10))
            if not 1 <= limit <= 50:
                raise ValueError("limit 必须是 1 到 50 之间的整数。")
            with self.security.admit(identity_keys):
                auth_queue_ms = int(
                    (time.perf_counter() - admitted_started) * 1000
                )
                parameters = inspect.signature(
                    self.service.search
                ).parameters
                if "request_id" in parameters:
                    search_options: dict[str, object] = {
                        "request_id": request_id,
                        "auth_queue_ms": auth_queue_ms,
                    }
                    if user_llm_key and "llm_api_key" in parameters:
                        search_options["llm_api_key"] = user_llm_key
                        user_llm_model = self.headers.get(
                            "X-ScholarPilot-LLM-Model"
                        )
                        if (
                            user_llm_model
                            and "llm_model" in parameters
                        ):
                            search_options["llm_model"] = user_llm_model
                    result = self.service.search(
                        query=query,
                        limit=limit,
                        **search_options,
                    )
                else:
                    result = self.service.search(
                        query=query,
                        limit=limit,
                    )
            self._send_json(result)
        except SecurityConfigurationError as exc:
            self._send_json(
                api_error(
                    code="backend_auth_not_configured",
                    message=str(exc),
                    request_id=request_id,
                ),
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        except AuthenticationError as exc:
            self._send_json(
                api_error(
                    code="unauthorized",
                    message=str(exc),
                    request_id=request_id,
                ),
                HTTPStatus.UNAUTHORIZED,
                {"WWW-Authenticate": "Bearer"},
            )
        except RateLimitExceeded as exc:
            self._send_json(
                api_error(
                    code="rate_limit_exceeded",
                    message=str(exc),
                    request_id=request_id,
                    retryable=True,
                    retry_after_seconds=exc.retry_after_seconds,
                ),
                HTTPStatus.TOO_MANY_REQUESTS,
                {"Retry-After": str(exc.retry_after_seconds)},
            )
        except ConcurrencyLimitExceeded as exc:
            self._send_json(
                api_error(
                    code="concurrency_limit_exceeded",
                    message=str(exc),
                    request_id=request_id,
                    retryable=True,
                    retry_after_seconds=1,
                ),
                HTTPStatus.TOO_MANY_REQUESTS,
                {"Retry-After": "1"},
            )
        except LiveSearchError as exc:
            if not exc.request_id:
                exc.request_id = request_id
            self._send_json(exc.to_api(), HTTPStatus.BAD_GATEWAY)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json(
                api_error(
                    code="invalid_request",
                    message=str(exc),
                    request_id=request_id,
                ),
                HTTPStatus.BAD_REQUEST,
            )
        except Exception:
            logger.exception("Unhandled POST /api/search failure")
            self._send_json(
                api_error(
                    code="internal_error",
                    message="服务器处理失败，请查看后端日志。",
                    request_id=request_id,
                    retryable=True,
                ),
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
