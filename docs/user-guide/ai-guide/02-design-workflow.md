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
- 需要在`shared_vars`中保留少量控制状态；
- AI工作与控制脚本需要独立State、Thread和失败边界。

不要为了运行一个Main Agent创建单Agent Workflow。Main Agent本身就是Agent Server root graph。

## 2. 两类执行机制

| 需求 | 机制 | State owner |
| --- | --- | --- |
| 模型推理、Tool loop、对话连续性 | Main Agent | Agent Thread checkpoint |
| Main Agent内部同步委派 | Deep Agents Subagent | 同一agent loop |
| 确定性计算、路由、外部API编排 | Workflow Command | Workflow `shared_vars` |
| 独立AI工作 | `runtime.context.agent_runs` | child Agent Thread |
| 独立控制流程 | `runtime.context.workflow_runs` | child Workflow Thread |
| 跨Thread共享artifact | 显式Store/Filesystem reference | 对应artifact owner |

Workflow不拥有Agent messages、conversation channel、dispatch task或Agent checkpoint。

## 3. Super-step和routing

Start Edge静态激活第一个Node。Command读取当前super-step State snapshot并返回：

```python
Command(
    update={"shared_vars": {...}},
    goto="<target-node-id>",
)
```

Command outgoing Edge声明允许的目标。compiler将这些目标作为`destinations`登记，真正执行由`goto`决定；不能再为Command添加static Edge。

一个Command可返回多个目标Node ID。并行目标读取同一super-step snapshot，更新在LangGraph边界按channel reducer合并。循环必须有业务退出条件；`recursion_limit`只是一条失败边界。

End映射官方`END`。Command省略goto时该path自然结束。

## 4. Workflow State

现行State只有：

```json
{
  "shared_vars": {}
}
```

`shared_vars`适合：

- route choice；
- child Run ID和operation ID；
- 少量结构化业务结果；
- loop计数和完成标志。

不适合：

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
result = (await runtime.context.agent_runs.join([handle.run_id]))[0]
```

默认创建新Thread。checkpoint enabled Agent可显式复用属于同一Agent的idle Thread，并创建新Run以续接对话；checkpoint disabled Agent使用stateless Run。

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
3. aggregation Command读取明确结果并更新`shared_vars`；
4. 通过goto进入下一个控制阶段。

Graph中的并行Node和独立Server Run不是同一层概念。需要独立Thread/Run identity时使用Run facade。

## 7. 设计记录

在创建配置前写下：

- 入口是Main Agent还是Workflow；
- 每个Command的输入、update和允许goto目标；
- `shared_vars`每个key的writer与reader；
- 每个child Run的target、operation ID和等待策略；
- 大型artifact的namespace/path与consumer；
- 每个循环退出条件；
- 请求入口的durability与on_disconnect策略；
- Agent如何获得初始messages以及是否需要续聊。

确认没有把Agent State搬进Workflow State后，再进入配置和Graph构建。
