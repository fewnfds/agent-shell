# 第三方组件与许可声明

Agent Shell 自身源码以 MIT 许可发布（根目录 `LICENSE`）。本页记录本项目与第三方组件的许可关系、二次开发边界，以及依赖升级时的复核入口。

逐项版本与许可明细见根目录 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)；该表由 `packaging/development/generate_third_party_notices.py` 按 `server/uv.lock`、`frontend/package-lock.json`、`packaging/windows/runtime-lock.json` 和 `packaging/windows/mcp-runtime-lock.json` 生成。

## LangGraph Agent Server 的使用条件

依赖闭包包含两个 Elastic-2.0 组件：`langgraph-api` 与 `langgraph-runtime-inmem`，由直接依赖和 `langgraph-cli[inmem]` 引入。Elastic-2.0 属于 source-available 许可，允许使用、复制、分发和修改，同时对下列行为设限：

| 使用方式 | 条件 |
| --- | --- |
| 在本机运行实例并自行使用 | 符合许可 |
| 把实例作为托管或管理服务提供给第三方，使第三方访问 Assistant、Thread、Run、State、Store 或 `/compat/openai/v1/*` 等实质功能 | 受 Elastic-2.0 限制，需另行获得授权 |
| 对外进行生产或自托管部署 | LangChain 要求 license key（`LANGGRAPH_CLOUD_LICENSE_KEY`） |

本项目不移动、更改、禁用或规避任何 license key 功能，也不更改、移除或遮蔽上游的许可、版权或其他声明。

本项目自身代码为 MIT；完整运行产物包含 Elastic-2.0 组件，对外描述该项目时使用“源码可见（source-available）”表述。

## 适配

| 项目 | 上游组件 | 现行做法 | 源码 owner |
| --- | --- | --- | --- |
| Subagent 空 SystemMessage 兼容 | `deepagents==0.7.19` | `create_sub_agent()` 在 declarative Subagent 未配置 prompt 时传入 `system_prompt=""`，产生的空 `SystemMessage` 会进入 Provider 请求。本项目在 Subagent middleware stack 装配 `EmptySystemMessageMiddleware`，只把内容为空字符串的 `SystemMessage` 投影为 `None`，非空 system content 保持原样。 | `server/src/agent_shell/runtime/deepagents_compatibility.py` |

`server/uv.lock` 安装的 Deep Agents wheel 保持原样。源码、开发虚拟环境和 portable runtime 均不修改 `site-packages/deepagents`；适配代码位于 `server/src/agent_shell/`，由 Git、测试和升级审查追踪。逐项接入清单见 [Deep Agents 公共组件接入清单](deep-agents-customizations.md)。

## 修改

| 项目 | 上游组件 | 现行做法 | 源码 owner |
| --- | --- | --- | --- |
| Windows curl-cffi BlockBuster 兼容 | `langgraph-runtime-inmem==0.34.1`（Elastic-2.0） | 包装 `langgraph_runtime_inmem.queue._enable_blockbuster`，在它返回的 blocker 上追加一条白名单：`socket.py::_fallback_socketpair`。 | `server/src/agent_shell/langgraph_dev.py` |

### 为什么要打这个补丁

LangGraph Dev 在共享事件循环上启用 BlockBuster：检测到阻塞 I/O 就直接报错，避免一个慢请求拖死整个服务。

Windows CPython 没有原生 `socketpair`，标准库 `socket.py` 用 `_fallback_socketpair` 先自连接再 `accept()`，以模拟一对通道。curl-cffi 为 Proactor event loop 建立 selector bridge 时会走到这段标准库代码，BlockBuster 把这次 `accept()` 判定为真实阻塞调用，服务在启动或请求阶段失败。

补丁保留 BlockBuster 的检测能力，只为 `socket.py::_fallback_socketpair` 这一条调用路径放行，其他 `socket.accept` 仍会被拦截。

### 生效条件

- 仅 Windows（`sys.platform == "win32"`）；
- 仅当【系统 / 系统配置 / Provider Network】选择 `provider_http.transport=curl_cffi` 时安装；标准 HTTPX 线路不装配该 hook；
- 包装保留原函数并用标记位保证幂等；直接测试位于 `test/runtime/test_langgraph_dev.py`。

### 升级复核

`_enable_blockbuster` 是上游私有符号。升级 `curl-cffi`、`httpx-curl-cffi` 或 LangGraph Dev runtime 时复核该边界；上游提供公开的放行手段后，删除本补丁及对应测试。

## 许可元数据缺失项

- `THIRD_PARTY_NOTICES.md` 中带 `†` 的行，是元数据没有机器可读许可表达的发行包；该值读取自对应版本 wheel 内附带的许可文件，并与包名、精确版本绑定。依赖升级后重跑生成脚本，这些行会回到 `NOASSERTION`，脚本同时在 stderr 报告过期条目，需要重新核对。
- `forbiddenfruit 0.1.4` 随包提供 GPL-3.0-or-later 与 MIT 两份许可文本，上游同时接受两种选择；本项目按 MIT 使用，运行时不修改它的源码。它由 `blockbuster` → `langgraph-runtime-inmem` 传递引入。
- MPL-2.0 组件（`certifi`、`pathspec`、`orjson`、`tqdm`）以未修改的依赖形式使用。依赖闭包中没有要求本项目整体按 copyleft 许可发布的组件。
- portable runtime 的 CPython（PSF-2.0）、Managed Local MCP 的内部 Node.js（MIT）与 uv（Apache-2.0 OR MIT）同样列在 `THIRD_PARTY_NOTICES.md` 中。

## 复核入口

修改任一依赖锁后重新生成声明，并确认没有再出现 `NOASSERTION`：

```powershell
server\.venv\Scripts\python.exe packaging\development\generate_third_party_notices.py
```
