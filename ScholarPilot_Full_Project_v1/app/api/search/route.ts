import { NextResponse } from "next/server";
import { runDemoSearch } from "@/app/lib/search";
import type { SearchMode } from "@/app/lib/types";

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

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const record = payload as Record<string, unknown>;
  if (typeof record.error === "string") return record.error;
  if (record.error && typeof record.error === "object") {
    const message = (record.error as Record<string, unknown>).message;
    if (typeof message === "string") return message;
  }
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const message = (detail as Record<string, unknown>).message;
    if (typeof message === "string") return message;
  }
  return fallback;
}

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      query?: string;
      mode?: SearchMode;
    };
    const query = body.query?.trim() ?? "";
    const mode = body.mode === "live" ? "live" : "demo";

    if (query.length < 6) {
      return NextResponse.json(
        { error: "请输入至少6个字符的科研检索问题。" },
        { status: 400 },
      );
    }
    if (query.length > 800) {
      return NextResponse.json(
        { error: "当前Demo最多接受800个字符。" },
        { status: 400 },
      );
    }

    if (mode === "live") {
      const proxyToken = process.env.BACKEND_PROXY_TOKEN?.trim() ?? "";
      if (proxyToken.length < 32) {
        return NextResponse.json(
          {
            error: {
              code: "live_proxy_not_configured",
              message:
                "实时检索代理未配置有效的 BACKEND_PROXY_TOKEN，"
                + "已安全拒绝请求。",
            },
          },
          { status: 502 },
        );
      }

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
            },
            body: JSON.stringify({ query, mode: "live", limit: 10 }),
            signal: AbortSignal.timeout(60_000),
          },
        );
        const payload = (await pythonResponse.json().catch(() => null)) as
          | Record<string, unknown>
          | null;
        if (pythonResponse.ok) {
          return NextResponse.json(payload);
        }
        if (pythonResponse.status === 400 || pythonResponse.status === 429) {
          return NextResponse.json(payload, {
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
              code: "live_backend_failed",
              message: errorMessage(
                payload,
                `Python 实时检索后端返回 HTTP ${pythonResponse.status}。`,
              ),
              upstreamStatus: pythonResponse.status,
            },
          },
          { status: 502 },
        );
      } catch (caught) {
        const timedOut =
          caught instanceof DOMException && caught.name === "TimeoutError";
        return NextResponse.json(
          {
            error: {
              code: timedOut
                ? "live_backend_timeout"
                : "live_backend_unreachable",
              message: timedOut
                ? "Python 实时检索后端超时。"
                : "无法连接 Python 实时检索后端。",
            },
          },
          { status: 502 },
        );
      }
    }

    const result = runDemoSearch(query);
    return NextResponse.json(result);
  } catch {
    return NextResponse.json(
      { error: "搜索请求解析失败，请稍后重试。" },
      { status: 500 },
    );
  }
}
