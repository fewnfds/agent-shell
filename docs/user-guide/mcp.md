# MCP 连接、映射与调用

Agent Shell 通过 LangChain 官方 `langchain-mcp-adapters` 把 MCP Server 公布的 Tool 转换成 LangChain `BaseTool`。MCP 不是一种固定 Tool，也没有要求服务器使用 Playwright、Node REPL 等“官方名称”；服务器在协议握手后公布自己的 Tool name、description 和 input schema，Agent 实际看到的是一组独立 Tool。

当前支持 stdio 与 Streamable HTTP。stdio 连接配置 command、按顺序保存的 args、可选绝对 cwd 和任意 env；Streamable HTTP 配置 HTTP(S) URL 和任意 Header。当前不提供 legacy SSE、WebSocket、OAuth、elicitation、自定义 transport 或共享 stateful session pool。

## 配置顺序

1. 在【代理组件 / MCP 要求】创建 Repository-owned `MCP Requirement`，填写说明和稳定 `namespace`。namespace 只允许字母、数字和下划线，且以字母或下划线开头；同一 Configuration Repository 内必须唯一。
2. 在【MCP / MCP 连接】创建 instance-owned `MCP Connection`。选择 stdio 或 Streamable HTTP，并填写真实连接参数。
3. 在【MCP / MCP 映射】把当前 Repository 的每个 MCP Requirement 绑定到本实例的一条 MCP Connection。
4. 在 Main Agent、Subagent 或【工作流组件 / Command 节点】的 MCP 要求 Card 中装配一个或多个 Requirement。每个调用方独立选择服务器全部 Tool，或只允许一组服务器原始 Tool name。

Requirement、Agent/Subagent/Command 引用属于 Configuration Repository，会进入 Configuration Bundle。Connection、映射和 secret 属于当前实例，不进入 Bundle。切换 Repository 后，映射页使用该 Repository 自己的 binding 分区。

## Tool 名称与选择

服务器原始 Tool name 不需要由 Agent Shell 预装或登记。例如服务器公布 `navigate`，Requirement namespace 为 `browser`，Agent 看到的 LangChain Tool name 是 `browser_navigate`。Tool description 和参数 schema 仍来自服务器，因此模型能够根据说明理解自定义名称。

选择【服务器全部 Tool】时，当前运行发现到的全部 Tool 都交给该 Agent 或 Subagent。选择【仅指定 Tool】时，配置填写服务器公布的原始名称，例如 `navigate`，不填写带 namespace 的最终名称；运行发现缺少任一已选名称会在模型调用前失败。不同 Main Agent、Subagent 和 Command 可以引用同一 Requirement，但保存不同 allowlist。

一次 Workflow Run 在构造 Agent Graph 前发现其所有引用的 MCP Tool。同一 Requirement 在该 Run 内只发现一次；Tool 调用沿用 adapter 的默认 stateless 行为，每次调用建立并关闭自己的 MCP session。Agent Shell 不包装服务器 Tool schema，也不把 MCP server instructions 自动加入 Agent prompt。

## 关闭 MCP

MCP 以 consumer 的 `mcp_refs` 是否为空作为启用边界。要让某个 Main Agent、Subagent 或 Command 不使用 MCP，在它的 MCP 要求 Card 中删除全部引用并保存。目标 Workflow 的所有可达 consumer 都没有 MCP 引用时，运行时不会创建 `MultiServerMCPClient`、不会执行 Tool discovery、不会连接 HTTP Server，也不会启动 stdio 子进程。

Connection、Mapping 和 Requirement 可以保留，供以后重新装配；它们本身不会主动连接。不要通过删除 Connection 或清除 Mapping 来代替关闭仍被引用的 MCP：引用代表 required dependency，残留引用会使 Workflow 在装配阶段以未绑定或连接缺失失败。当前没有额外的实例级总开关；需要整实例停用时，清空所有 Main Agent、Subagent 和 Command 的 `mcp_refs`。

## Secret 与普通配置

每个 stdio env 或 HTTP Header 都单独选择【密钥】或【普通配置】：

- 普通配置值保存在 `data/config/mcp-connections/<uuid>.yaml`，管理 API 会回传；
- 密钥值只保存在 `data/config/agent-shell.env`，Connection YAML 只保存引用，管理 API 只返回 `masked` 或 `missing`；
- 编辑已配置密钥时留空会保留原值；改名或新增 secret slot 时必须填写新值；
- stdio env 与 HTTP Header 是不同通道；切换 Connection transport 会清空旧通道的配置行，需要按新 transport 重新填写；
- Connection URL 不接受内嵌 username/password，secret 不进入 Repository、Bundle、State、checkpoint 或普通日志。

这里的 `agent-shell.env` 是 Agent Shell 自己的实例 secret store，不会把 MCP env 自动提升成服务进程的全局环境。对于 stdio Server，运行时只把当前 Connection 已解析的 env 交给该子进程；HTTP Header 只进入对应 MCP 请求。

## 导入 mcpServers JSON

【MCP / MCP 连接 / 导入 JSON】接受通行的顶层格式：

```json
{
  "mcpServers": {
    "browser": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": {
        "SERVICE_TOKEN": "replace-me"
      }
    },
    "remote-search": {
      "type": "streamable-http",
      "url": "https://example.com/mcp",
      "headers": {
        "Authorization": "Bearer replace-me"
      }
    }
  }
}
```

`type`/`transport` 的 `http` 与 `streamable_http`/`streamable-http` 会规范化为 Streamable HTTP；省略 transport 时，有 `url` 的条目按 HTTP，其余按 stdio。Preview 列出每个 env/Header，用户逐项选择 secret 或 literal 后一次提交。整批导入原子完成，任何条目无效或名称冲突时不创建部分 Connection。

导入只创建 Connection，不创建 Requirement、映射或 Agent/Command 引用，也不持续同步原 JSON。`${VAR}` 形式的未解析环境引用会被拒绝；请在导入前提供真实值，并在 Preview 中选择 secret 存储。当前只接受上述两个 transport 的语义字段，避免悄悄忽略 OAuth、SSE、WebSocket 或其他未实现行为。

## Command Node 调用

Command package 的 `async command(state, runtime)` 从受限的 `runtime.context.mcp` facade 调用自己装配的 MCP。未装配 MCP 时该值为 `None`；它不暴露底层 client、session、Connection 或 secret。

```python
async def command(state, runtime):
    mcp = runtime.context.mcp
    if mcp is None:
        return {"update": {}, "activate": [], "dispatch": []}

    tools = mcp.available_tools()
    result = await mcp.call_tool(
        "browser",
        "navigate",
        {"url": "https://example.com"},
    )
    if result.status == "error":
        raise RuntimeError(str(result.content))
    return {
        "update": {"shared_vars": {"browser_result": result.content}},
        "activate": [],
        "dispatch": [],
    }
```

`available_tools()` 返回 `namespace -> raw Tool names`。`call_tool(namespace, tool_name, arguments)` 只能调用当前 Command allowlist 内的 Tool，并返回 LangChain `ToolMessage`；脚本通过 `status == "success"|"error"` 区分 MCP 执行结果，读取 `content` 和可选 `artifact`。transport、session 与内容转换异常仍直接抛出。`get_resources(namespace, uris=...)` 与 `get_prompt(namespace, prompt_name, arguments=...)` 保留 adapter 的官方返回对象；它们要求该 namespace 已装配，但 Resource/Prompt 不会伪装成 Agent Tool。

Custom Tool 不额外获得 MCP client 或 facade。Agent 使用装配后的标准 `BaseTool`，Command 使用上述窄 facade，二者共用同一个 Run-local discovery 事实来源。
