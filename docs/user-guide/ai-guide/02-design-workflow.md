# 设计 Workflow

本章用于决定任务应由Main Agent直接完成，还是由Workflow控制多个独立Graph Run。完成结果是一份只包含确定性control step、State字段和退出条件的设计记录。

## 1. 先选择入口Graph

直接使用Main Agent：

- 主要工作是一个连续agent loop；
- 模型自行选择Tool或同步Subagent即可完成；
- 对话需要在同一Thread的后续Run延续；
- 不需要由确定性脚本控制多个独立Run。

使用Workflow：

- 需要可审计的确定性顺序、条件、循环或外部系统步骤；
- 需要显式start/check/join/cancel独立Main Agent或Workflow Run；
- 需要在 state、store、file 甚至外部 database 中保留状态机控制状态或数据；
- AI工作与控制脚本需要独立State、Thread和失败边界。

不要为了运行一个Main Agent创建单Agent Workflow。Main Agent本身就是Agent Server root graph。

## 2. 两类执行机制

| 需求 | 机制 | State owner |
| --- | --- | --- |
| 模型推理、Tool loop、对话连续性 | Main Agent | Agent Thread checkpoint |
| Main Agent内部同步委派 | Deep Agents Subagent | 同一agent loop |
| 确定性计算、路由、外部API编排 | Workflow Command | Workflow 扁平变量表 |
| 独立AI工作 | `runtime.context.agent_runs` | child Agent Thread |
| 独立控制流程 | `runtime.context.workflow_runs` | child Workflow Thread |
| 跨Thread共享artifact | 显式Store/Filesystem reference | 对应artifact owner |

Workflow不拥有Agent messages、conversation channel、dispatch task或Agent checkpoint。

## 3. Super-step和routing

Start Edge静态激活第一个Node。Command读取当前super-step State snapshot并返回：

```python
Command(
    update={...},
    goto="<target-node-id>",
)
```

Command outgoing Edge声明允许的目标。compiler将这些目标作为`destinations`登记，真正执行由`goto`决定；不能再为Command添加static Edge。

一个Command可返回多个目标Node ID。并行目标读取同一super-step snapshot，更新在LangGraph边界按channel reducer合并。循环必须有业务退出条件；`recursion_limit`只是一条失败边界。

End映射官方`END`。Command省略goto时该path自然结束。

## 4. Workflow State

State 是一张扁平的变量表，键名由你自己决定：

```json
{
  "selected_target": "publish",
  "item_count": 2
}
```

Command 读用 `state.get("selected_target")`，写用 `Command(update={"selected_target": ...})`。
没有额外嵌套层。

入口传入的键和 Command 写回的键都保留在同一个 checkpoint 里，同一个键以最后
一次写回结果为准。

Workflow 提供一个可选的 `state_schema`（JSON Schema，根节点必须声明
`"type": "object"`）：

- 不声明：任何 JSON 键都能读写，不做键名与类型校验；
- 声明：入口输入和每个 Command 的 update 结果都按它校验；不符合的输入在 Run
  启动前失败，不符合的 update 让 Run 以 `workflow.state_invalid` 失败。

适合放进 State 的内容：

- route choice；
- child Run ID和operation ID；
- 少量结构化业务结果；
- loop计数和完成标志。

不适合放进 State 的内容见下一节。

- Agent消息历史；
- 原始event/token日志；
- 官方Run status/time/error的持续副本；
- 大型正文、数据集或二进制；
- 其他Thread的完整State。

大型结果写入Store或mapped Filesystem，只在State传递稳定reference。

## 5. 调用Main Agent

Command通过Run facade创建独立Agent：

```python
handle = await runtime.context.agent_runs.start(
    "<main-agent-uuid>",
    [{"role": "user", "content": "Research the supplied topic."}],
    operation_id="research:topic-42",
)
result = await runtime.context.agent_runs.join(handle.thread_id, handle.run_id)
```

默认创建新Thread。Agent可显式复用属于同一Agent的idle Thread，并创建新Run以续接对话。

`operation_id`在current caller Run内幂等。脚本应从稳定业务identity生成它，避免Node retry重复派遣。

## 6. 常用topology

固定顺序：

```text
START -> prepare -> execute -> finish -> END
```

条件：

```text
START -> decide
           | goto=approved -> publish -> END
           | goto=rejected -> revise --+
                  ^---------------------+
```

并行独立Run：

1. 一个Command依次调用多个`agent_runs.start`并保存handles；
2. 后续Command执行其他确定性工作或`join`；
3. aggregation Command读取明确结果并写回 State；
4. 通过goto进入下一个控制阶段。

Graph中的并行Node和独立Server Run不是同一层概念。需要独立Thread/Run identity时使用Run facade。

## 7. 设计记录

在创建配置前写下：

- 入口类型是Agent还是Workflow；Agent入口对应哪个Main Agent；
- 每个Command的输入、update和允许goto目标；
- State 每个key的writer与reader；
- 每个child Run的target、operation ID和等待策略；
- 大型artifact的namespace/path与consumer；
- 每个循环退出条件；
- 请求入口的on_disconnect策略；
- Agent如何获得初始messages以及是否需要续聊。

确认没有把Agent State搬进Workflow State后，再进入配置和Graph构建。
