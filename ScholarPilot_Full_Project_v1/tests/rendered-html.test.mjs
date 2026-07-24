import assert from "node:assert/strict";
import test from "node:test";

const developmentPreviewMeta =
  /<meta(?=[^>]*\bname=["']codex-preview["'])(?=[^>]*\bcontent=["']development["'])[^>]*>/i;

test("renders development preview metadata", async () => {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  const response = await worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );

  assert.equal(response.status, 200);
  assert.match(
    response.headers.get("content-type") ?? "",
    /^text\/html\b/i,
  );
  assert.match(await response.text(), developmentPreviewMeta);
});

test("returns a ranked deterministic demo search", async () => {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("search-test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  const response = await worker.fetch(
    new Request("http://localhost/api/search", {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        query:
          "寻找2024—2026年使用查询分解进行复杂学术论文检索的LLM Agent论文",
        mode: "demo",
      }),
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );

  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /application\/json/i);
  const payload = await response.json();
  assert.equal(payload.schemaVersion, "1.0");
  assert.equal(payload.status, "success");
  assert.ok(payload.requestId);
  assert.equal(payload.mode, "demo");
  assert.equal(payload.provider, "内置比赛演示数据");
  assert.ok(payload.plan.subqueries.length >= 2);
  assert.ok(payload.results.length >= 5);
  assert.equal(payload.results[0].rank, 1);
  assert.ok(payload.results[0].score >= payload.results[1].score);
  assert.ok(payload.stats.candidateCount >= payload.results.length);
  assert.equal(payload.stats.llmCalls, 0);
  assert.ok(payload.stats.stageTimings);
  assert.equal(payload.sourceStatus[0].source, "demo");
});

test("live search fails closed and never falls back to demo papers", async () => {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("live-security-test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  const response = await worker.fetch(
    new Request("http://localhost/api/search", {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        query: "academic paper retrieval agent query decomposition",
        mode: "live",
      }),
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );

  assert.equal(response.status, 502);
  const payload = await response.json();
  assert.equal(payload.error.code, "live_proxy_not_configured");
  assert.ok(payload.error.requestId);
  assert.equal(payload.error.retryable, false);
  assert.equal("results" in payload, false);
});
