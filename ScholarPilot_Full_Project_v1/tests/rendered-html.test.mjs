import assert from "node:assert/strict";
import test from "node:test";

const developmentPreviewMeta =
  /<meta(?=[^>]*\bname=["']codex-preview["'])(?=[^>]*\bcontent=["']development["'])[^>]*>/i;

async function loadWorker(label) {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set(label, `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker;
}

const bindings = {
  ASSETS: {
    fetch: async () => new Response("Not found", { status: 404 }),
  },
};

const context = {
  waitUntil() {},
  passThroughOnException() {},
};

test("renders development preview metadata", async () => {
  const worker = await loadWorker("render-test");
  const response = await worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    bindings,
    context,
  );

  assert.equal(response.status, 200);
  assert.match(
    response.headers.get("content-type") ?? "",
    /^text\/html\b/i,
  );
  assert.match(await response.text(), developmentPreviewMeta);
});

test("rejects an invalid query before contacting Python", async () => {
  const worker = await loadWorker("validation-test");
  const response = await worker.fetch(
    new Request("http://localhost/api/search", {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({ query: "short" }),
    }),
    bindings,
    context,
  );

  assert.equal(response.status, 400);
  const payload = await response.json();
  assert.equal(payload.error.code, "invalid_query");
  assert.ok(payload.error.requestId);
  assert.equal("results" in payload, false);
});

test("search fails closed when the Python proxy is not configured", async () => {
  const worker = await loadWorker("security-test");
  const response = await worker.fetch(
    new Request("http://localhost/api/search", {
      method: "POST",
      headers: {
        accept: "application/json",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        query: "academic paper retrieval agent query decomposition",
      }),
    }),
    bindings,
    context,
  );

  assert.equal(response.status, 502);
  const payload = await response.json();
  assert.equal(payload.error.code, "live_proxy_not_configured");
  assert.ok(payload.error.requestId);
  assert.equal(payload.error.retryable, false);
  assert.equal("results" in payload, false);
});
