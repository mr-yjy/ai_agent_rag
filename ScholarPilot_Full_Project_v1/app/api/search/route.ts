import { NextResponse } from "next/server";
import {
  isSearchResponse,
  protocolError,
  readApiError,
} from "@/app/lib/api-schema";
import {
  DEFAULT_USER_LLM_MODEL,
  isUserLlmModel,
} from "@/app/lib/llm-models";
import type { ApiErrorResponse } from "@/app/lib/types";

export const runtime = "edge";

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL || "http://127.0.0.1:8000";

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
    const payload = await request.json() as unknown;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return NextResponse.json(
        errorResponse(
          "invalid_request",
          "请求体必须是 JSON 对象。",
          requestId,
        ),
        { status: 400 },
      );
    }

    const body = payload as Record<string, unknown>;
    const unexpectedFields = Object.keys(body).filter(
      (key) => key !== "query" && key !== "limit",
    );
    if (unexpectedFields.length > 0) {
      return NextResponse.json(
        errorResponse(
          "invalid_request",
          `请求包含不支持的字段：${unexpectedFields.join(", ")}。`,
          requestId,
        ),
        { status: 400 },
      );
    }

    const query = typeof body.query === "string" ? body.query.trim() : "";
    const limit = body.limit === undefined ? 10 : Number(body.limit);

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
    if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
      return NextResponse.json(
        errorResponse(
          "invalid_limit",
          "limit 必须是 1 到 50 之间的整数。",
          requestId,
        ),
        { status: 400 },
      );
    }

    const userLlmKey =
      request.headers.get("x-scholarpilot-llm-key")?.trim() ?? "";
    const requestedUserLlmModel =
      request.headers.get("x-scholarpilot-llm-model")?.trim() ?? "";
    if (!userLlmKey) {
      return NextResponse.json(
        errorResponse(
          "llm_api_key_required",
          "请先在网页设置中添加你的 DeepSeek API Key。",
          requestId,
        ),
        { status: 400 },
      );
    }
    if (
      userLlmKey.length < 16
      || userLlmKey.length > 512
      || /\s/.test(userLlmKey)
    ) {
      return NextResponse.json(
        errorResponse(
          "invalid_llm_api_key",
          "DeepSeek API Key 格式无效。",
          requestId,
        ),
        { status: 400 },
      );
    }
    if (
      requestedUserLlmModel
      && !isUserLlmModel(requestedUserLlmModel)
    ) {
      return NextResponse.json(
        errorResponse(
          "invalid_llm_model",
          "DeepSeek 模型无效或缺少个人 API Key。",
          requestId,
        ),
        { status: 400 },
      );
    }
    const userLlmModel = requestedUserLlmModel || DEFAULT_USER_LLM_MODEL;

    const proxyToken = process.env.BACKEND_PROXY_TOKEN?.trim() ?? "";
    if (proxyToken.length < 32) {
      return NextResponse.json(
        errorResponse(
          "live_proxy_not_configured",
          "实时检索代理未配置有效的 BACKEND_PROXY_TOKEN，"
            + "已安全拒绝请求。",
          requestId,
        ),
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
            ...(userLlmKey
              ? {
                  "X-ScholarPilot-LLM-Key": userLlmKey,
                  "X-ScholarPilot-LLM-Model": userLlmModel,
                }
              : {}),
          },
          body: JSON.stringify({ query, limit }),
          signal: upstreamSignal,
        },
      );
      const pythonPayload = await pythonResponse.json().catch(() => null);
      if (pythonResponse.ok) {
        if (!isSearchResponse(pythonPayload)) {
          return NextResponse.json(protocolError(requestId), {
            status: 502,
          });
        }
        return NextResponse.json(pythonPayload);
      }
      if (pythonResponse.status === 400 || pythonResponse.status === 429) {
        const normalized = {
          error: readApiError(
            pythonPayload,
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
              pythonPayload,
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
