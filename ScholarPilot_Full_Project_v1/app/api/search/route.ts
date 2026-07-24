import { NextResponse } from "next/server";
import {
  isSearchResponse,
  protocolError,
  readApiError,
} from "@/app/lib/api-schema";
import { runDemoSearch } from "@/app/lib/search";
import type {
  ApiErrorResponse,
  SearchMode,
} from "@/app/lib/types";

export const runtime = "edge";

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || "http://127.0.0.1:8000";

function requestClientIp(request: Request): string {
  const raw =
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-real-ip") ||
    request.headers.get("x-forwarded-for")?.split(",", 1)[0] ||
    "";
  return raw.trim().replace(/[^0-9a-fA-F:.]/g, "").slice(0, 64);
}

async function requestIdentity(request: Request): Promise<string> {
  const rawIdentity =
    request.headers.get("oai-authenticated-user-email") ||
    request.headers.get("cf-connecting-ip") ||
    request.headers.get("x-real-ip") ||
    request.headers.get("x-forwarded-for")?.split(",", 1)[0] ||
    "anonymous";
  const bytes = new TextEncoder().encode(rawIdentity.trim().toLowerCase());
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .slice(0, 16)
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function errorResponse(
  code: string,
  message: string,
  requestId: string,
  options: {
    retryable?: boolean;
    retryAfterSeconds?: number;
    stage?: string;
  } = {},
): ApiErrorResponse {
  return {
    error: {
      code,
      message,
      requestId,
      retryable: options.retryable ?? false,
      retryAfterSeconds: options.retryAfterSeconds ?? 0,
      stage: options.stage,
    },
  };
}

export async function POST(request: Request) {
  const requestId = crypto.randomUUID();
  try {
    const body = (await request.json()) as {
      query?: string;
      mode?: SearchMode;
    };
    const query = body.query?.trim() ?? "";
    const mode = body.mode === "live" ? "live" : "demo";

    if (query.length < 6) {
      return NextResponse.json(
        errorResponse(
          "invalid_query",
          "请输入至少6个字符的科研检索问题。",
          requestId,
        ),
        { status: 400 },
      );
    }
    if (query.length > 800) {
      return NextResponse.json(
        errorResponse(
          "invalid_query",
          "当前接口最多接受800个字符。",
          requestId,
        ),
        { status: 400 },
      );
    }

    if (mode === "live") {
      const proxyToken = process.env.BACKEND_PROXY_TOKEN?.trim() ?? "";
      if (proxyToken.length < 32) {
        return NextResponse.json(
          {
            ...errorResponse(
              "live_proxy_not_configured",
              "实时检索代理未配置有效的 BACKEND_PROXY_TOKEN，"
                + "已安全拒绝请求。",
              requestId,
            ),
          },
          { status: 502 },
        );
      }

      const timeoutSignal = AbortSignal.timeout(55_000);
      const upstreamSignal = AbortSignal.any([
        request.signal,
        timeoutSignal,
      ]);
      try {
        const pythonResponse = await fetch(
          `${PYTHON_BACKEND_URL}/api/search`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${proxyToken}`,
              "X-ScholarPilot-User": await requestIdentity(request),
              "X-Forwarded-For": requestClientIp(request),
              "X-Request-ID": requestId,
            },
            body: JSON.stringify({ query, mode: "live", limit: 10 }),
            signal: upstreamSignal,
          },
        );
        const payload = await pythonResponse.json().catch(() => null);
        if (pythonResponse.ok) {
          if (!isSearchResponse(payload)) {
            return NextResponse.json(protocolError(requestId), {
              status: 502,
            });
          }
          return NextResponse.json(payload);
        }
        if (pythonResponse.status === 400 || pythonResponse.status === 429) {
          const normalized = {
            error: readApiError(
              payload,
              `Python 后端返回 HTTP ${pythonResponse.status}。`,
              requestId,
            ),
          };
          return NextResponse.json(normalized, {
            status: pythonResponse.status,
            headers:
              pythonResponse.status === 429
                ? {
                    "Retry-After":
                      pythonResponse.headers.get("Retry-After") || "1",
                  }
                : undefined,
          });
        }
        return NextResponse.json(
          {
            error: {
              ...readApiError(
                payload,
                `Python 实时检索后端返回 HTTP ${pythonResponse.status}。`,
                requestId,
              ),
              upstreamStatus: pythonResponse.status,
            },
          },
          { status: 502 },
        );
      } catch {
        const timedOut = timeoutSignal.aborted && !request.signal.aborted;
        const cancelled = request.signal.aborted;
        return NextResponse.json(
          errorResponse(
            cancelled
              ? "search_cancelled"
              : timedOut
                ? "live_backend_timeout"
                : "live_backend_unreachable",
            cancelled
              ? "搜索请求已取消。"
              : timedOut
                ? "Python 实时检索后端超过 55 秒总时限。"
                : "无法连接 Python 实时检索后端。",
            requestId,
            {
              retryable: true,
              stage: timedOut ? "frontend_proxy" : undefined,
            },
          ),
          { status: cancelled ? 499 : 502 },
        );
      }
    }

    const result = runDemoSearch(query, requestId);
    return NextResponse.json(result);
  } catch {
    return NextResponse.json(
      errorResponse(
        "invalid_request",
        "搜索请求解析失败，请检查 JSON 格式。",
        requestId,
      ),
      { status: 400 },
    );
  }
}
