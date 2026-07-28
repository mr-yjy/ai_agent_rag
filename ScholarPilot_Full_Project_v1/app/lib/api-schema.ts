import type {
  ApiError,
  ApiErrorResponse,
  SearchResponse,
} from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : fallback;
}

export class NonJsonResponseError extends Error {
  readonly status: number;
  readonly contentType: string;

  constructor(status: number, contentType: string) {
    super(
      `Expected a JSON API response, but received ${
        contentType || "an unknown content type"
      } (HTTP ${status || "unknown"}).`,
    );
    this.name = "NonJsonResponseError";
    this.status = status;
    this.contentType = contentType;
  }
}

export async function readJsonResponse(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();
  try {
    return JSON.parse(body) as unknown;
  } catch {
    throw new NonJsonResponseError(response.status, contentType);
  }
}

export function readApiError(
  payload: unknown,
  fallback: string,
  fallbackRequestId: string,
): ApiError {
  if (!isRecord(payload)) {
    return {
      code: "invalid_error_response",
      message: fallback,
      requestId: fallbackRequestId,
      retryable: true,
      retryAfterSeconds: 0,
    };
  }
  const rawError = isRecord(payload.error)
    ? payload.error
    : isRecord(payload.detail)
      ? payload.detail
      : payload;
  return {
    code: stringValue(rawError.code, "request_failed"),
    message: stringValue(rawError.message, fallback),
    requestId: stringValue(rawError.requestId, fallbackRequestId),
    retryable: rawError.retryable === true,
    retryAfterSeconds: Math.max(
      0,
      numberValue(rawError.retryAfterSeconds),
    ),
    stage: stringValue(rawError.stage) || undefined,
    upstreamStatus: numberValue(rawError.upstreamStatus) || undefined,
  };
}

export function isSearchResponse(payload: unknown): payload is SearchResponse {
  if (!isRecord(payload)) return false;
  if (payload.schemaVersion !== "1.0") return false;
  if (typeof payload.requestId !== "string" || !payload.requestId) return false;
  if (!["success", "no_results", "degraded"].includes(String(payload.status))) {
    return false;
  }
  if (typeof payload.provider !== "string") return false;
  if (!isRecord(payload.queryPlan) || !isRecord(payload.plan)) return false;
  if (!Array.isArray(payload.results) || !Array.isArray(payload.sourceStatus)) {
    return false;
  }
  if (!isRecord(payload.stats)) return false;
  if (payload.reliability !== undefined) {
    if (!isRecord(payload.reliability)) return false;
    if (
      !["completed", "skipped", "failed"].includes(
        stringValue(payload.reliability.status),
      )
      || ![
        "ACCEPT",
        "RETRY_RETRIEVAL",
        "RETRY_REASONING",
        "ABSTAIN",
        "NOT_RUN",
      ].includes(stringValue(payload.reliability.decision))
      || typeof payload.reliability.confidence !== "number"
    ) {
      return false;
    }
  }
  const stats = payload.stats;
  return (
    typeof stats.elapsedMs === "number"
    && typeof stats.apiCalls === "number"
    && typeof stats.llmCalls === "number"
    && isRecord(stats.stageTimings)
    && isRecord(stats.tokenUsage)
    && typeof stats.stopReason === "string"
    && typeof stats.configHash === "string"
  );
}

export function protocolError(
  requestId: string,
  message = "后端响应缺少 v1.0 Schema 的必填字段。",
): ApiErrorResponse {
  return {
    error: {
      code: "invalid_search_schema",
      message,
      requestId,
      retryable: true,
      retryAfterSeconds: 0,
    },
  };
}
