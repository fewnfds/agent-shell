# Response Stream Scheduling

Response Stream Scheduling 是可复用的 Workflow Component，使用现有 Configuration Repository 和配置库 CRUD 管理。Parent Run Workflow 通过可空 `response_stream_scheduling_id` 装配一个配置；未装配时使用下表中的内置默认。Child Run Workflow 不拥有该引用。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 必填 | 配置库中的组件名称 |
| `queue.strategy` | `request\|node_invocation` | `request` | 选择 AI request 或一次 Node invocation 作为输出原子 |
| `queue.idle_timeout_seconds` | number >= 0 | `2` | 当前原子多久没有新的非空公开文本后让位；每次非空输出都会重新计时 |
| `queue.max_batch_kb` | number > 0 | `64` | 一批已排序输出的 UTF-8 软大小；至少发送一个完整项，单项可越过该值 |
| `queue.send_interval_seconds` | number >= 0 | `0.05` | 首批之后相邻传输批次的最小间隔 |

`request`原子的`message-finish`只结束正文block，因为同一次request之后仍可能等待Tool outcome。同一invocation的下一次model request开始或所属Node terminal时，前一个request已有输出排完后立即让位；idle timeout只处理仍无确定后继边界的静默或慢Tool等待。

创建配置：

```http
POST /api/blocks/response-stream-scheduling
```

```json
{
  "name": "Fair response stream",
  "queue": {
    "strategy": "request",
    "idle_timeout_seconds": 2,
    "max_batch_kb": 64,
    "send_interval_seconds": 0.05
  }
}
```

保存 response 中的组件 UUID，再写入 Parent Workflow metadata 的 `response_stream_scheduling_id`。组件引用会进入 Repository validation、copy 和 Configuration Bundle 依赖闭包；请求启动时从同一冻结 Repository 快照解析。删除组件不会改写引用方 UUID，Repository validation 会报告缺失引用。

本组件只负责已经由 Agent Event Output 或 Workflow Event Output 批准的文本排序、Tool transaction 原子性、合批和节流发送。事件是否输出、正文内容和首尾修饰仍由对应 Event Output 唯一决定。当前调度输入来自 Parent Run；independent child/background Run events 是否接入保持待定。
