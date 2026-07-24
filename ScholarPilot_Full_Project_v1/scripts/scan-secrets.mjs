import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const scanHistory = process.argv.includes("--history");
const artifactFlag = process.argv.indexOf("--artifact");
const artifactRoot =
  artifactFlag >= 0 && process.argv[artifactFlag + 1]
    ? resolve(process.argv[artifactFlag + 1])
    : null;
const credentialNames = new Set([
  "LLM_API_KEY",
  "DEEPSEEK_API_KEY",
  "OPENALEX_API_KEY",
  "SEMANTIC_SCHOLAR_API_KEY",
  "BACKEND_PROXY_TOKEN",
]);
const placeholderMarkers = [
  "your-",
  "your_",
  "example",
  "placeholder",
  "optional",
  "test-key",
  "changeme",
  "replace-me",
  "这里填写",
  "你的",
  "<",
  "${",
];
const findings = [];
const findingKeys = new Set();

function git(args, options = {}) {
  const result = spawnSync("git", args, {
    encoding: "utf8",
    maxBuffer: 128 * 1024 * 1024,
    ...options,
  });
  if (result.status !== 0) {
    const message = (result.stderr || result.stdout || "git failed").trim();
    throw new Error(message);
  }
  return result.stdout;
}

function isPlaceholder(value) {
  const normalized = value
    .trim()
    .replace(/^["']|["']$/g, "")
    .toLowerCase();
  return (
    !normalized ||
    normalized.startsWith("#") ||
    placeholderMarkers.some((marker) => normalized.includes(marker))
  );
}

function addFinding({ source, ref, path, line, rule }) {
  const key = `${source}:${ref}:${path}:${line}:${rule}`;
  if (findingKeys.has(key)) return;
  findingKeys.add(key);
  findings.push({ source, ref, path, line, rule });
}

function scanLine(text, location) {
  const assignment = text.match(
    /^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$/,
  );
  if (
    assignment &&
    credentialNames.has(assignment[1]) &&
    !isPlaceholder(assignment[2])
  ) {
    addFinding({ ...location, rule: `non-empty-${assignment[1]}` });
  }

  const genericMatches = text.match(/\bsk-[A-Za-z0-9_-]{24,}\b/g) || [];
  for (const candidate of genericMatches) {
    if (!isPlaceholder(candidate)) {
      addFinding({ ...location, rule: "generic-sk-credential" });
    }
  }
}

function scanTrackedTree() {
  const files = git(["ls-files", "-z"]).split("\0").filter(Boolean);
  for (const path of files) {
    let content;
    try {
      content = readFileSync(path, "utf8");
    } catch {
      continue;
    }
    content.split(/\r?\n/).forEach((line, index) => {
      scanLine(line, {
        source: "worktree",
        ref: "HEAD",
        path,
        line: index + 1,
      });
    });
  }
}

function scanArtifact(root) {
  const visit = (path) => {
    const stat = statSync(path);
    if (stat.isDirectory()) {
      for (const entry of readdirSync(path)) {
        visit(resolve(path, entry));
      }
      return;
    }
    if (!stat.isFile() || stat.size > 16 * 1024 * 1024) return;
    let content;
    try {
      content = readFileSync(path, "utf8");
    } catch {
      return;
    }
    content.split(/\r?\n/).forEach((line, index) => {
      scanLine(line, {
        source: "artifact",
        ref: "local",
        path: path.replace(`${root}\\`, "").replace(`${root}/`, ""),
        line: index + 1,
      });
    });
  };
  visit(root);
}

function scanGitHistory() {
  const history = git([
    "log",
    "--all",
    "--format=__COMMIT__%H",
    "--no-ext-diff",
    "-p",
    "--",
    ".",
  ]);
  let commit = "unknown";
  let path = "unknown";
  let patchLine = 0;
  for (const line of history.split(/\r?\n/)) {
    if (line.startsWith("__COMMIT__")) {
      commit = line.slice("__COMMIT__".length);
      path = "unknown";
      patchLine = 0;
      continue;
    }
    if (line.startsWith("+++ b/")) {
      path = line.slice(6);
      patchLine = 0;
      continue;
    }
    if (!line.startsWith("+") || line.startsWith("+++")) continue;
    patchLine += 1;
    scanLine(line.slice(1), {
      source: "history",
      ref: commit.slice(0, 12),
      path,
      line: patchLine,
    });
  }
}

if (artifactRoot) {
  scanArtifact(artifactRoot);
} else {
  scanTrackedTree();
}
if (scanHistory) scanGitHistory();

if (findings.length) {
  console.error(`Secret scan failed: ${findings.length} redacted finding(s).`);
  for (const finding of findings) {
    console.error(
      `${finding.source}:${finding.ref}:${finding.path}:${finding.line}:${finding.rule}`,
    );
  }
  process.exitCode = 1;
} else {
  console.log(
    artifactRoot
      ? "Secret scan passed: client artifact has zero findings."
      : scanHistory
      ? "Secret scan passed: tracked tree and full Git history have zero findings."
      : "Secret scan passed: tracked tree has zero findings.",
  );
}
