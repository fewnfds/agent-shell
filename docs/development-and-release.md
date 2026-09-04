# 开发与版本

## 运行通道

| 场景 | 后端 | 前端 | 入口 |
| --- | --- | --- | --- |
| 滚动源码 Clone | 当前 `server/src/` | 输入变化时自动 build | `start_server.bat` |
| 前端 Debug | 当前 `server/src/` | Vite HMR | `packaging/development/start_dev.ps1` |

`frontend/` 是唯一前端源码。production 产物只生成到 Git 忽略的 `runtime/frontend_dist/`，不进入 `server/src/`，避免源码搜索读取生成 bundle。

## 分支

- `dev`：唯一的 Git 分支和 GitHub 默认分支，承载滚动源码与日常集成；每次推送保持可启动；
- `v<project.version>` tag：从 `dev` 创建，标记正式源码版本；
- 发布修复直接提交到 `dev`，通过版本 tag 标记发布点。

源码维护目录不作为用户实例运行。滚动用户使用独立 Clone，并保留该 Clone 自己的 `data/`。

## 源码运行

Windows 10/11 x64 需要 Node.js 22，不需要预装 Python。启动脚本按 `packaging/windows/runtime-lock.json` 在 `runtime/app` 准备固定的内置 CPython 3.12 和锁定依赖，后端直接读取当前源码；前端输入变化时执行锁定的 npm build。项目只维护这套内置解释器，不声明兼容宿主 Python。

最终服务进程由锁定的 `langgraph dev --no-reload` 启动。现有 FastAPI 作为 custom app 与官方 Assistant、Thread、Run、State 和 Store route 共用同一个 `host:port`；普通启动不创建第二个 API listener。只有系统设置显式配置 `debug_port` 时才额外创建 DAP 调试 listener。LangGraph Dev 的运行目录固定为实例 `data/state/langgraph-dev/`。

```powershell
.\start_server.bat
```

当前 Clone 的 `data/config/` 首次初始化时，源码启动器要求确认并以输入 `y` 继续；已初始化的 Clone 直接进入启动流程。

更新前停止服务：

```powershell
git pull --ff-only
.\start_server.bat
```

依赖和前端使用输入指纹刷新。普通 Python、文档或配置修改不会无条件重建整个 runtime。

停止服务后可以整体移动 Windows 运行 Clone。启动器根据自身位置重新解析源码、`data/` 和 `runtime/`；
`runtime/cache` 保存可重建的下载缓存；安装位置由启动器根据当前 Clone 解析。

文件化 Python 配置扩展中的 `requirements.txt` 不写入 `server/pyproject.toml`，而由 Windows 启动器按可达配置指纹生成 `runtime/python_packages/site-packages`。启用 Workflow 可达集包含 Command、Main Agent/Subagent 引用的 Custom Tool、Custom Middleware、Agent Event Output 和 Workflow Event Output 扩展；静态模板和未触达的配置扩展不参与，输入未变化时复用。扩展层只能增加与核心锁兼容的二进制 wheel，不能修改 `runtime/app`。启动设置初始化与读取合并为一次 preflight；扩展依赖准备在最终服务进程内、应用创建前完成，避免为了相邻启动步骤重复拉起并导入 Python 应用。

依赖准备开始时终端先显示当前 requirements，随后直接显示 uv 原生的解析、下载、安装进度和错误；完成后才显示服务启动阶段。启动器不为扩展依赖安装设置主动超时，操作者根据终端中的真实进度决定继续等待、换网络或中止重启。

## 当前运行时与依赖基线

当前运行基线由两个锁共同决定：`packaging/windows/runtime-lock.json` 锁定 Windows portable runtime，
`server/uv.lock` 锁定 Python wheel。当前稳定基线为：

| 层 | 当前版本 |
| --- | --- |
| 内置 CPython | `3.12.13` |
| runtime/CI uv | `0.12.2` |
| Deep Agents | `0.7.11` |
| FastAPI / Uvicorn | `0.141.1` / `0.52.1` |
| LangChain adapters | Anthropic `1.7.0`；DeepSeek `1.1.0`；Google GenAI `4.3.7`；Google Vertex AI `3.2.4`；OpenAI `1.6.0`；xAI `1.3.0` |
| LangChain core/graph | `langchain 1.3.18`；`langchain-core 1.6.1`；`langgraph 1.2.11`；LangSmith `0.11.2` |
| LangGraph Dev | CLI `0.4.31`；API `0.13.3`；in-memory runtime `0.33.3`；SDK `0.4.4` |
| 其他边界 | `packaging 26.3`；`websockets 15.0.1`；dev-only `httpx2/httpcore2 2.9.1` |

第三方声明见 [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。修改任一依赖锁、`packaging/windows/runtime-lock.json` 或 `packaging/windows/mcp-runtime-lock.json` 后，在 `server/.venv` 已按锁同步的环境中运行 `packaging/development/generate_third_party_notices.py` 并提交生成结果。`mcp-runtime-lock.json` 只锁定 Managed Local npm MCP 按需使用的内部 Node.js，不进入核心 Python runtime fingerprint；前端源码构建使用的 Node.js 22 仍由开发机提供。

无范围的 `uv lock --upgrade` 会把 FastAPI、Provider SDK 和开发依赖等无关行为面一起带入，不作为日常升级入口。依赖升级先用 `uv tree --outdated` 扫描，再按单一影响面使用 scoped `--upgrade-package` 推进。LangChain 系的版本边界、LangSmith `>=0.11.2,<0.12` 的理由和下一次复核步骤见[LangChain 系依赖升级](langchain-dependency-upgrades.md)。

## 前端 Debug

### 前端页面组合

管理台页面按稳定组合接入：`PageShell` 提供管理台内容壳和底部操作区；配置库页面使用 `ConfigurationLibraryFrame` 与 `useConfigurationCatalog`；配置编辑页面使用 `ConfigurationEditorLayout`、`ConfigurationCrudActions` 和 `CopyNameModal`。页面保留自己的领域表单、草稿状态和 management API/service 编排，不重复创建相同的导航、左右工作区、CRUD action dock 或复制弹窗。表格页面直接提供 `DataTableConfig` 给 `DataTableWorkbench`。

只有需要 HMR 时使用隔离启动器。它分配临时 loopback 端口和临时 data，不读取正常实例数据：

```powershell
$pythonHome = (Get-Content .\runtime\app\python-home.txt -Raw).Trim()
$python = Join-Path (Join-Path .\runtime\app $pythonHome) python.exe
pwsh.exe -NoProfile -File .\packaging\development\start_dev.ps1 `
  -ProjectRoot $PWD -PythonExe $python
```

自动化 Debug 可以显式传入仓库外的本地凭据文件。文件必须位于源码树外，第一行必须是非空、无空格的 `0x21-0x7E` 可打印 ASCII，并仅用于隔离 Debug；
启动器将它同时用作临时 management token 和临时 API key，且不会打印内容。未传参数时仍分别生成随机凭据。

```powershell
$credentialFile = Join-Path $env:LOCALAPPDATA 'AgentShell\codex-debug-token.txt'
pwsh.exe -NoProfile -File .\packaging\development\start_dev.ps1 `
  -ProjectRoot $PWD -PythonExe $python -CredentialFile $credentialFile
```

## 验证

按改动风险选择最接近的一项，不把所有检查固定串联：

```powershell
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

```powershell
cd server
.\.venv\Scripts\python.exe -m pytest ..\test\<domain>\test_relevant_module.py -q
.\.venv\Scripts\python.exe ..\test\smoke_http.py
```

首次准备开发依赖时在 `server/` 显式使用项目自带的 uv 与 CPython，避免 PATH 上其他软件附带的 uv 或用户目录中的 Python 被写入 `.venv`：

```powershell
$pythonHome = (Get-Content ..\runtime\app\python-home.txt -Raw).Trim()
$python = Join-Path (Join-Path ..\runtime\app $pythonHome) python.exe
& ..\runtime\bootstrap\uv.exe sync --python $python --extra dev --frozen --no-python-downloads
```

之后的日常定向 pytest 直接使用项目 `.venv`。测试会在 session startup 校验 `agent_shell` 的实际来源必须是当前仓库的 `server/src/agent_shell`；如果系统 Python 或用户级 editable 安装把其他项目注入 `sys.path`，测试会立即失败，不会静默执行错误源码。避免每轮测试都让 `uv` 重复检查环境。pytest 临时文件使用 Windows 系统临时目录，不在源码目录设置 `basetemp`；同时禁用 pytest cache provider，避免生成仓库内 `.pytest_cache`。不要为一次局部改动运行完整 `test/`。大量 TestClient 用例会分别创建隔离 data root 和 SQLite，Windows 杀毒软件与目录索引会放大这类全量运行的磁盘成本。

永久测试按职责放入 `test/api_server/`、`test/authoring/`、`test/runtime/`、`test/security/` 或 `test/architecture/`；共享 fixture 与测试支撑代码保存在 `test/fixtures/` 和 `test/` 的直接支撑模块中。
用户可观察行为、API 和持久化结果是验收证据。

推送 `dev` 时，GitHub Actions 运行一次无凭据的确定性门禁：前端 lint、typecheck、UI policy 与 Vitest，以及后端 `test/` 下由 pytest 默认收集的 `test_*.py`。本地需要复现完整门禁时使用：

```powershell
cd frontend
npm run lint
npm run typecheck
npm run ui:check
npm test
```

```powershell
cd server
.\.venv\Scripts\python.exe -m pytest ..\test -q
```

`test/smoke_http.py` 通过显式命令运行。默认 pytest 集合用于确定性测试，真实 Provider 与 Agent eval 使用各自的显式入口。GitHub Actions 执行完整 pytest 门禁；普通局部修改运行最接近的 contract owner。本地复现完整门禁时使用上面的 `.venv\Scripts\python.exe -m pytest ..\test -q` 命令。

## 源码版本

版本权威字段是 `server/pyproject.toml` 的 `project.version`。tag 必须为 `v<project.version>`。

创建版本 tag 前：

```powershell
git status --short
git diff --check
```

当前阶段的维护与复核以 Windows 源码 Clone 启动方式为准。修改 Windows runtime bootstrap、依赖锁或启动入口时，
按本页的源码 Clone 启动方式复核。

确认 `dev` 后创建 annotated tag：

```powershell
git push origin dev
git tag -a v<version> -m "release: v<version>"
git push origin v<version>
```

已公开 tag 不移动；修复后更新项目版本并创建新 tag。
