import { NextResponse } from "next/server";
import { runSearch } from "@/app/lib/search";
import type { SearchMode } from "@/app/lib/types";

export const runtime = "edge";

export async function POST(request: Request) {
  try {
    const body = (await request.json()) as {
      query?: string;
      mode?: SearchMode;
    };
    const query = body.query?.trim() ?? "";
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

    const result = await runSearch(
      query,
      body.mode === "live" ? "live" : "demo",
    );
    return NextResponse.json(result);
  } catch {
    return NextResponse.json(
      { error: "搜索请求解析失败，请稍后重试。" },
      { status: 500 },
    );
  }
}

