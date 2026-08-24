# 检查点保存器（Checkpointer）

检查点保存器是 Workflow-owned Component。它使用官方 LangGraph `AsyncSqliteSaver` 为明确引用它的 Workflow Run 保存 State 检查点；Workflow metadata 通过可空 `checkpointer_id` 选择配置，默认值为 `null`，表示不启用。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 必填 | 当前 Component type 内唯一的显示名称 |
| `durability` | `exit \| async \| sync` | `async` | LangGraph 的检查点写入时机 |

- `exit`：Graph 正常结束、报错或触发 interrupt 时写入；运行期开销最低，进程崩溃会丢失尚未保存的中间状态；
- `async`：下一步执行时异步写入当前检查点；在延迟与持久性之间取默认平衡；
- `sync`：完成当前检查点写入后再开始下一步；持久性最强，写入延迟最高。

选择后，每个 Workflow Run 都生成自己的 `checkpoint_thread_id`。Canvas Agent/Deep Agent subgraph 按 LangGraph 默认继承所在 Workflow root 的 saver。parent Workflow 与 background child Workflow 分别读取自己的配置。

未选择时，Graph 不传 checkpoint thread 或 durability，也不会因该 Run 启动 saver。最终 State、Store、Lifecycle、Run/Event/Model Request History、Agent invocation artifact、background Run、Tracing、Diagnostics 和 usage 保持可用；Checkpoint State、Checkpoint Thread 和检查点计数自然不存在。当前软件只使用检查点做 Debug，不提供 Resume、time travel 或灾难恢复入口。
