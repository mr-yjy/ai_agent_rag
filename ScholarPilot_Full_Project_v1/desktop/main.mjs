import {
  app,
  BrowserWindow,
  ipcMain,
  safeStorage,
  session,
  shell,
} from "electron";
import { spawn } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import {
  createReadStream,
  existsSync,
  promises as fs,
} from "node:fs";
import { createServer } from "node:http";
import {
  dirname,
  extname,
  join,
  resolve,
  sep,
} from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = dirname(fileURLToPath(import.meta.url));
const projectRoot = resolve(moduleDirectory, "..");
const rendererPort = 17845;
const rendererOrigin = `http://127.0.0.1:${rendererPort}`;
const allowedModels = new Set([
  "deepseek-v4-pro",
  "deepseek-v4-flash",
]);
const mimeTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml"],
  [".webp", "image/webp"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
]);

let backendProcess = null;
let desktopServer = null;
let backendBaseUrl = "";
let proxyToken = "";
let mainWindow = null;
let quitting = false;

async function writeSmokeState(stage, details = {}) {
  const smokeFile =
    process.env.SCHOLARPILOT_DESKTOP_SMOKE_FILE?.trim();
  if (!smokeFile) return;
  await fs.writeFile(
    smokeFile,
    JSON.stringify({ stage, ...details }),
    "utf8",
  );
}

function settingsPath() {
  return join(app.getPath("userData"), "deepseek-settings.json");
}

function validateSettings(settings) {
  const apiKey =
    typeof settings?.apiKey === "string" ? settings.apiKey.trim() : "";
  const model =
    typeof settings?.model === "string" ? settings.model.trim() : "";
  if (
    apiKey.length < 16
    || apiKey.length > 512
    || /\s/.test(apiKey)
  ) {
    throw new Error("DeepSeek API Key 格式无效。");
  }
  if (!allowedModels.has(model)) {
    throw new Error("DeepSeek 模型无效。");
  }
  return { apiKey, model };
}

function assertTrustedSender(event) {
  const senderUrl = event.senderFrame?.url ?? "";
  if (!senderUrl.startsWith(`${rendererOrigin}/`)) {
    throw new Error("拒绝来自非 ScholarPilot 窗口的设置请求。");
  }
}

async function loadSettings() {
  if (!safeStorage.isEncryptionAvailable()) return null;
  try {
    const payload = JSON.parse(
      await fs.readFile(settingsPath(), "utf8"),
    );
    const encrypted = Buffer.from(payload.encryptedApiKey, "base64");
    const apiKey = safeStorage.decryptString(encrypted);
    const settings = validateSettings({ apiKey, model: payload.model });
    return settings;
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw new Error("无法读取本机保存的 DeepSeek 设置。");
  }
}

async function saveSettings(settings) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error("Windows 安全存储当前不可用。");
  }
  const normalized = validateSettings(settings);
  const encryptedApiKey = safeStorage
    .encryptString(normalized.apiKey)
    .toString("base64");
  await fs.mkdir(dirname(settingsPath()), { recursive: true });
  await fs.writeFile(
    settingsPath(),
    JSON.stringify(
      {
        schemaVersion: 1,
        encryptedApiKey,
        model: normalized.model,
      },
      null,
      2,
    ),
    { encoding: "utf8", mode: 0o600 },
  );
}

async function clearSettings() {
  await fs.rm(settingsPath(), { force: true });
}

function registerSettingsBridge() {
  ipcMain.handle("desktop-settings:load", async (event) => {
    assertTrustedSender(event);
    return loadSettings();
  });
  ipcMain.handle("desktop-settings:save", async (event, settings) => {
    assertTrustedSender(event);
    await saveSettings(settings);
    return { ok: true };
  });
  ipcMain.handle("desktop-settings:clear", async (event) => {
    assertTrustedSender(event);
    await clearSettings();
    return { ok: true };
  });
}

function backendExecutable() {
  if (app.isPackaged) {
    return {
      command: join(
        process.resourcesPath,
        "backend",
        "ScholarPilotBackend.exe",
      ),
      arguments: ["--host", "127.0.0.1", "--port", "0"],
      cwd: join(process.resourcesPath, "backend"),
    };
  }
  return {
    command: process.env.SCHOLARPILOT_PYTHON || "python",
    arguments: [
      join(projectRoot, "backend", "run.py"),
      "--host",
      "127.0.0.1",
      "--port",
      "0",
    ],
    cwd: join(projectRoot, "backend"),
  };
}

async function startBackend() {
  proxyToken = randomBytes(48).toString("base64url");
  const executable = backendExecutable();
  if (!existsSync(executable.command) && app.isPackaged) {
    throw new Error("客户端内置的 ScholarPilot 后端不存在。");
  }

  return new Promise((resolveStart, rejectStart) => {
    let stdoutBuffer = "";
    let stderrBuffer = "";
    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      rejectStart(
        new Error(
          `本机检索后端启动超时。${stderrBuffer.slice(-500)}`,
        ),
      );
    }, 20_000);

    backendProcess = spawn(
      executable.command,
      executable.arguments,
      {
        cwd: executable.cwd,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          BACKEND_PROXY_TOKEN: proxyToken,
          CORS_ALLOWED_ORIGINS: rendererOrigin,
          LLM_API_KEY: "",
          DEEPSEEK_API_KEY: "",
        },
      },
    );

    backendProcess.stdout.on("data", (chunk) => {
      stdoutBuffer += chunk.toString("utf8");
      const match = stdoutBuffer.match(
        /ScholarPilot backend: (http:\/\/127\.0\.0\.1:\d+)/,
      );
      if (!match || settled) return;
      settled = true;
      clearTimeout(timeout);
      backendBaseUrl = match[1];
      resolveStart();
    });
    backendProcess.stderr.on("data", (chunk) => {
      stderrBuffer = `${stderrBuffer}${chunk.toString("utf8")}`.slice(
        -2_000,
      );
    });
    backendProcess.once("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      rejectStart(error);
    });
    backendProcess.once("exit", (code) => {
      backendProcess = null;
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      rejectStart(
        new Error(`本机检索后端提前退出（代码 ${code ?? "unknown"}）。`),
      );
    });
  });
}

function setSecurityHeaders(response) {
  response.setHeader(
    "Content-Security-Policy",
    [
      "default-src 'self'",
      "base-uri 'none'",
      "connect-src 'self'",
      "font-src 'self' data:",
      "form-action 'self'",
      "frame-ancestors 'none'",
      "img-src 'self' data: https:",
      "object-src 'none'",
      "script-src 'self'",
      "style-src 'self' 'unsafe-inline'",
    ].join("; "),
  );
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("X-Frame-Options", "DENY");
}

async function readRequestBody(request, limit = 1_000_000) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > limit) throw new Error("请求体过大。");
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

async function proxyApiRequest(request, response, pathname) {
  const allowed =
    (pathname === "/api/health" && request.method === "GET")
    || (pathname === "/api/search" && request.method === "POST");
  if (!allowed) {
    response.writeHead(405, {
      "Content-Type": "application/json; charset=utf-8",
    });
    response.end(JSON.stringify({ error: { code: "method_not_allowed" } }));
    return;
  }

  try {
    const body =
      request.method === "POST" ? await readRequestBody(request) : undefined;
    const upstream = await fetch(`${backendBaseUrl}${pathname}`, {
      method: request.method,
      headers: {
        Authorization: `Bearer ${proxyToken}`,
        "Content-Type": "application/json",
        "X-Forwarded-For": "127.0.0.1",
        "X-Request-ID": randomUUID(),
        "X-ScholarPilot-User": "desktop-local-user",
        ...(request.headers["x-scholarpilot-llm-key"]
          ? {
              "X-ScholarPilot-LLM-Key":
                request.headers["x-scholarpilot-llm-key"],
            }
          : {}),
        ...(request.headers["x-scholarpilot-llm-model"]
          ? {
              "X-ScholarPilot-LLM-Model":
                request.headers["x-scholarpilot-llm-model"],
            }
          : {}),
      },
      body,
      signal: AbortSignal.timeout(56_000),
    });
    const payload = Buffer.from(await upstream.arrayBuffer());
    setSecurityHeaders(response);
    response.writeHead(upstream.status, {
      "Content-Type":
        upstream.headers.get("content-type")
        || "application/json; charset=utf-8",
      ...(upstream.headers.get("retry-after")
        ? { "Retry-After": upstream.headers.get("retry-after") }
        : {}),
    });
    response.end(payload);
  } catch {
    setSecurityHeaders(response);
    response.writeHead(502, {
      "Content-Type": "application/json; charset=utf-8",
    });
    response.end(
      JSON.stringify({
        error: {
          code: "desktop_backend_unreachable",
          message: "无法连接本机 ScholarPilot 检索后端。",
          retryable: true,
          requestId: randomUUID(),
        },
      }),
    );
  }
}

async function serveStatic(response, pathname) {
  const rendererRoot = app.isPackaged
    ? join(app.getAppPath(), "desktop-dist", "renderer")
    : join(projectRoot, "desktop-dist", "renderer");
  const relativePath =
    pathname === "/" ? "index.html" : decodeURIComponent(pathname.slice(1));
  const absolutePath = resolve(rendererRoot, relativePath);
  if (
    absolutePath !== rendererRoot
    && !absolutePath.startsWith(`${rendererRoot}${sep}`)
  ) {
    response.writeHead(403);
    response.end();
    return;
  }

  let selectedPath = absolutePath;
  try {
    const stat = await fs.stat(selectedPath);
    if (!stat.isFile()) throw new Error("not_file");
  } catch {
    selectedPath = join(rendererRoot, "index.html");
  }
  setSecurityHeaders(response);
  response.writeHead(200, {
    "Cache-Control":
      extname(selectedPath) === ".html"
        ? "no-store"
        : "public, max-age=31536000, immutable",
    "Content-Type":
      mimeTypes.get(extname(selectedPath).toLowerCase())
      || "application/octet-stream",
  });
  createReadStream(selectedPath).pipe(response);
}

async function startDesktopServer() {
  desktopServer = createServer(async (request, response) => {
    const requestUrl = new URL(
      request.url || "/",
      rendererOrigin,
    );
    if (requestUrl.pathname.startsWith("/api/")) {
      await proxyApiRequest(request, response, requestUrl.pathname);
      return;
    }
    if (!["GET", "HEAD"].includes(request.method || "")) {
      response.writeHead(405);
      response.end();
      return;
    }
    await serveStatic(response, requestUrl.pathname);
  });

  await new Promise((resolveListen, rejectListen) => {
    desktopServer.once("error", rejectListen);
    desktopServer.listen(
      rendererPort,
      "127.0.0.1",
      resolveListen,
    );
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 930,
    minWidth: 980,
    minHeight: 700,
    backgroundColor: "#0c1624",
    icon: join(app.getAppPath(), "desktop", "assets", "icon.ico"),
    autoHideMenuBar: true,
    show: false,
    title: "研索智航 · ScholarPilot",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: join(moduleDirectory, "preload.cjs"),
      sandbox: true,
      webSecurity: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(`${rendererOrigin}/`)) event.preventDefault();
  });
  mainWindow.once("ready-to-show", () => mainWindow?.show());
  mainWindow.webContents.once("did-finish-load", () => {
    console.log("SCHOLARPILOT_DESKTOP_READY");
    const smokeFile =
      process.env.SCHOLARPILOT_DESKTOP_SMOKE_FILE?.trim();
    if (smokeFile) {
      void writeSmokeState(
        "window_ready",
        {
          ready: true,
          rendererOrigin,
          backendBaseUrl,
        },
      );
    }
    if (process.env.SCHOLARPILOT_DESKTOP_SMOKE_TEST === "1") {
      setTimeout(() => app.quit(), 8_000);
    }
  });
  void mainWindow.loadURL(rendererOrigin);
}

async function shutdown() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.destroy();
    mainWindow = null;
  }
  if (desktopServer) {
    const server = desktopServer;
    desktopServer = null;
    await new Promise((resolveClose) => {
      server.close(() => resolveClose());
      server.closeAllConnections();
    });
  }
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", (event) => {
    if (quitting) return;
    event.preventDefault();
    quitting = true;
    void shutdown().finally(() => app.exit(0));
  });

  async function bootstrap() {
    await writeSmokeState("module_loaded");
    await app.whenReady();
    await writeSmokeState("electron_ready");
    session.defaultSession.setPermissionRequestHandler(
      (_webContents, _permission, callback) => callback(false),
    );
    registerSettingsBridge();
    try {
      await startBackend();
      await writeSmokeState("backend_ready", { backendBaseUrl });
      await startDesktopServer();
      await writeSmokeState("renderer_server_ready", {
        rendererOrigin,
      });
      createWindow();
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "客户端启动失败。";
      console.error(message);
      await writeSmokeState("failed", {
        ready: false,
        error: message,
      });
      await shutdown();
      app.exit(1);
    }
  }

  void bootstrap();
}
