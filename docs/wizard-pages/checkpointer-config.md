# 检查点保存器（Checkpointer）

检查点保存器是 Workflow-owned Component。它使用官方 LangGraph `AsyncSqliteSaver` 为明确引用它的 Workflow Run 保存 State 检查点；Workflow metadata 通过可空 `checkpointer_id` 选择配置，默认值为 `null`，表示不启用。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 必填 | 当前 Component type 内唯一的显示名称 |
| `durability` | `exit \| async \| sync` | `async` | LangGraph 的检查点写入时机 |

- `exit`：Graph 正常结束、报错或触发 interrupt 时写入；运行期开销最低，进程崩溃会丢失尚未保存的中间状态；
- `async`：下一步执行时异步写入当前检查点；在延迟与持久性之间取默认平衡；
- `sync`：完成当前检查点写入后再开始下一步；持久性最强，写入延迟最高。

Server-managed Workflow Run 的 Thread、checkpoint、State 与 history 当前由 LangGraph Dev runtime 统一拥有，执行路径不读取 Workflow 的 `checkpointer_id`。该配置面将在 persistence 阶段收敛；当前配置任务不应依赖本组件改变运行行为。
当前软件不提供 State history、修改、Resume、time travel 或灾难恢复入口。
