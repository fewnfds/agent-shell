# 系统提示词

```json
{"name": "Concise assistant", "system_prompt": "Be concise."}
```

`system_prompt` 必填，最多 200,000 字符。Main Agent 选择后作为 `create_deep_agent(system_prompt=...)` 的基础提示；Subagent 可以继承、替换或关闭。Middleware 仍可在 ModelRequest 阶段调整有效 system message。
