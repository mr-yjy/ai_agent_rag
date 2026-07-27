# ScholarPilot Windows 客户端 MVP

桌面客户端复用 ScholarPilot 网页界面，但不会连接 ScholarPilot 公网后端。
Electron 在本机启动：

1. 一个仅监听 `127.0.0.1:17845` 的界面服务器；
2. 一个监听随机本机端口的 Python 检索后端；
3. 一个每次启动重新生成的内部代理令牌。

用户的 DeepSeek API Key 使用 Electron `safeStorage` 加密。在 Windows
上该能力由当前 Windows 账户保护。密钥不会写入项目 `.env`，也不会
发送到 ScholarPilot 公网服务。

客户端仍需联网访问 DeepSeek、OpenAlex 和 Semantic Scholar。

## 本地运行

要求：

- Node.js 22.13 或更高版本；
- Python 3.11 或更高版本；
- 已安装项目 npm 依赖。

```powershell
npm.cmd run desktop:run
```

开发模式会直接使用 `backend/run.py`。

## 生成 Windows 安装包

首次打包需要安装 PyInstaller：

```powershell
pip install "pyinstaller>=6.10,<7"
```

随后运行：

```powershell
npm.cmd run desktop:package
```

输出位于 `desktop-release/`。未签名的 MVP 安装包可能触发 Windows
SmartScreen 提示；正式公开发布前应配置代码签名证书和可信更新渠道。

## 安全边界

- 前端和后端只绑定 `127.0.0.1`；
- 桌面端不读取服务端 `LLM_API_KEY` 或 `DEEPSEEK_API_KEY`；
- Python 后端仍要求随机代理令牌；
- Electron 启用上下文隔离、渲染器沙箱和严格 CSP；
- 外部论文链接只允许交给系统浏览器打开；
- 关闭窗口时会停止本机 HTTP 服务和 Python 子进程。
