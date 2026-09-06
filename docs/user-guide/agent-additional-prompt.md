# Agent Additional Prompt

Agent Additional Prompt（AAP）是一个普通Custom Middleware模板，用于在Main Agent Thread第一次进入agent loop时，从明确来源构造初始messages。

## 为什么只初始化一次

Stateful Main Agent的messages由AgentState和Thread checkpoint拥有。同一Thread上的后续Run会加载已有messages；如果AAP每次Run都附加原始请求，历史会重复。

内置模板在Middleware private state中保存checkpointed initialization marker：

1. marker不存在时读取输入、构造messages并同时写入marker；
2. marker存在时返回空update；
3. LangGraph在super-step checkpoint中保存messages与marker；
4. 同一Thread的新Run从该checkpoint继续。

`checkpoint_mode=disabled`的stateless Run没有跨Run State，因此每次独立Run都会重新初始化，这与stateless语义一致。

## 输入来源

Main Agent从current AgentState的`messages`读取本次Run input。模板复制并验证这些消息，再按配置决定裁剪、排序和role编排。Lifecycle request snapshot仍可通过`runtime.context.lifecycle_id`从`runtime.store`显式读取，但内置模板不需要用它建立第二份消息来源。

Subagent由Deep Agents传入delegated messages，默认直接保留该输入。AAP不读取其他Thread checkpoint，也不从Workflow State寻找Agent conversation。

需要跨Run或跨Thread的业务材料时，使用有明确namespace、writer和reader的Server Store artifact或mapped Filesystem reference，并在AAP代码中显式选择；不要镜像完整AgentState。

## 创建与装配

1. 在【代理组件 / Custom Middleware】从`内置示例-agent-additional-prompt`创建配置。
2. 编辑该配置独占package中的材料选择函数。
3. 在Main Agent或Subagent的ordered Middleware列表中加入该配置。
4. 通过Middleware顺序决定它与其他`before_agent` hook的相对位置。

模板入口仍是标准LangChain Middleware：

```python
class AgentAdditionalPromptMiddleware(AgentMiddleware):
    async def abefore_agent(self, state, runtime):
        ...
```

所有Store、Filesystem和网络I/O保持async；同步库只在该资源唯一owner处用`asyncio.to_thread()`隔离。

## 边界

- AAP只决定Agent第一次可见的messages，不改变system prompt、Event Output或Workflow routing。
- marker属于Agent private State，不属于Workflow或Lifecycle Store索引。
- Thread是连续性identity；Run只是一次执行。
- 配置删除或修改不回写已经存在的Thread checkpoint。
- AAP扩展运行在服务进程的受信任边界内，没有sandbox。
