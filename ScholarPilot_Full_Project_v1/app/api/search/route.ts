import { NextResponse } from "next/server";
import { runSearch } from "@/app/lib/search";
import type { SearchMode } from "@/app/lib/types";

export const runtime = "edge";

const PYTHON_BACKEND_URL = process.env.PYTHON_BACKEND_URL || "http://127.0.0.1:8000";

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

    // Try Python backend first for live mode
    if (mode === "live" && process.env.USE_PYTHON_BACKEND === "true") {
      try {
        const pythonResponse = await fetch(
          `${PYTHON_BACKEND_URL}/api/search`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, mode: "live", limit: 10 }),
            signal: AbortSignal.timeout(60_000),
          },
        );
        if (pythonResponse.ok) {
          const data = await pythonResponse.json();
          return NextResponse.json(data);
        }
      } catch {
        // Fall through to built-in search
        console.warn("[Search API] Python backend unavailable, using built-in");
      }
    }

    // Built-in search (supports both demo and live/fallback)
    const result = await runSearch(query, mode);
    return NextResponse.json(result);
  } catch {
    return NextResponse.json(
      { error: "搜索请求解析失败，请稍后重试。" },
      { status: 500 },
    );
  }
}
