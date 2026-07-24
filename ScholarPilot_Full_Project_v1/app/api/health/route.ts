import { NextResponse } from "next/server";

export const runtime = "edge";

const PYTHON_BACKEND_URL =
  process.env.PYTHON_BACKEND_URL || "http://127.0.0.1:8000";

export async function GET() {
  try {
    const response = await fetch(`${PYTHON_BACKEND_URL}/api/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    const payload = (await response.json()) as Record<string, unknown>;
    if (!response.ok) {
      throw new Error(`Python health returned HTTP ${response.status}`);
    }
    return NextResponse.json({
      ...payload,
      frontend: {
        service: "scholarpilot-web",
        livePath: "python-proxy-only",
      },
    });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        ready: false,
        frontend: {
          service: "scholarpilot-web",
          livePath: "python-proxy-only",
        },
        backend: {
          status: "unreachable",
          urlConfigured: Boolean(PYTHON_BACKEND_URL),
        },
        error: {
          code: "backend_health_unreachable",
          message: "无法读取 Python 后端健康状态。",
        },
      },
      { status: 502 },
    );
  }
}
