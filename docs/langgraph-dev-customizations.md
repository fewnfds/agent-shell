# LangGraph Dev 持久化二次开发

Agent Shell 使用原生 Windows 单进程 `langgraph dev --no-reload`，由根目录
`start_server.bat` 一键启动。系统配置提供 Core resource 保存间隔和仅变化时写盘设置。
该能力由 Agent Shell 适配 LangGraph Dev 的私有接口实现，属于项目维护的二次开发；
LangGraph 官方公共 CLI 当前没有这两个配置项。

## 用户设置

【系统 / 系统配置 / LangGraph Dev】包含 DAP 调试端口、保存间隔和仅在内容变化时写盘。
保存间隔使用带“秒”单位的整数输入框，写盘策略使用是/否下拉框，复用该 Card 的 Save。
保存后显示重启提示，重启服务后采用新值。完整用户规则见
[系统设置](user-guide/system-management.md#系统设置)。

```yaml
# data/config/system.yaml
settings:
  langgraph_persistence:
    flush_interval_seconds: 10
    write_if_changed: true
```

| 字段 | 默认值 | 有效值与行为 |
| --- | --- | --- |
| `flush_interval_seconds` | `10` | 正整数秒，最小 `1`；最大为当前 CPython 的 `int(threading.TIMEOUT_MAX)`，Windows 内置 CPython 3.12 为 `4294967`。该上界来自 `threading.Event.wait()` 的平台超时边界，超出会产生 `OverflowError` |
| `write_if_changed` | `true` | `true`：序列化结果与上次成功提交相同时跳过写盘；`false`：每次检查都保存完整快照 |

`PUT /agent-shell/api/system/settings` 的完整 payload 包含 `langgraph_persistence`。
后端拒绝非整数、零、负数、超平台边界的间隔，以及非布尔策略；API 返回 `422`，
原保存值保持。手工配置文件中的无效值使启动失败，并报告字段与原因。

增大间隔可减少序列化和写盘次数，也会拉长异常退出时可能丢失的 Core resource
修改窗口。实际间距还包含序列化、提交和系统调度耗时。正常退出仍执行最后一次同步；
进程强制结束、磁盘错误或断电不能依赖该同步。

## 当前维护边界

`server/uv.lock` 安装的 wheel 与 `site-packages` 保持原样。适配集中在
`server/src/agent_shell/langgraph_dev_persistence.py`，仅由 launcher
`__main__._run_server()` 在进入官方 CLI 前安装，并在 CLI 退出后恢复。

当前验证基线：`langgraph-runtime-inmem==0.34.3`、`langgraph-checkpoint==4.3.0`，
配套 API `0.14.6`、CLI `0.4.33`。适配入口对前两个直接使用私有实现的包做精确版本校验；
版本不匹配时启动失败并指向本页。维护者完成升级复核后才能更新 `_VERIFIED_VERSIONS`。

| 接入点 | 当前职责 | 升级必须复核 |
| --- | --- | --- |
| `langgraph_runtime_inmem._persistence._flush_interval` | 配置后台检查间隔 | 类型、计时方式和配置入口 |
| `_persistence._flush_loop`、`_stores`、`stop_flush_loop()` | 停止 import 阶段的 fallback Store 线程；pool 注册后启动配置循环；失败记录异常并于下个周期重试；退出时停止线程 | import side effect、注册/注销、weakref、线程重启、停止和异常行为 |
| `database.GLOBAL_STORE.sync` | 保存 Assistant、Thread、Run、Assistant version 与 Cron 等 Core resource 的官方序列化结果 | 实例身份、文件位置、嵌套 mutation、`dump()`/`load()` 和 `close()` |
| `database.GLOBAL_RETRY_COUNTER._counters.sync` | 对官方 retry counter 使用相同写盘策略 | counter 生命周期、类型、文件与关闭路径 |
| `langgraph.checkpoint.memory.PersistentDict` 的 `dump()`、`flag`、`filename`、`mode` | 使用官方格式和读写属性；替换两个指定实例的 `sync` | 序列化格式、只读语义、权限与 `close -> sync -> clear` 顺序 |
| `database.start_pool()` / `stop_pool()` | 继续由官方负责载入、注册与最终同步 | startup/lifespan 顺序、shutdown 同步是否在线程中执行 |

Core resource 的语义、公开 SDK/API 和文件格式继续由 Agent Server 拥有。
checkpoint、State/history 与 Server Store 分别使用官方 `AsyncSqliteSaver` 和
`AsyncSqliteStore`，按各自 transaction 提交；这两个 SQLite factory 的持久化频率独立于上述设置。
项目只向 writer 传递官方 dump 产生的字节，不解析 pickle，不重定义 Thread/Run schema，
也不替换所有 `PersistentDict` 实例或建立第二套资源数据库。

## 保存算法与失败边界

1. runtime 的 package import 会为 fallback in-memory Store 注册持久字典并启动线程。
   适配入口先停止该线程、安装间隔和 writer；随后由官方 pool 注册 Core resource
   store，启动配置后的 persistence 后台线程。
2. 每轮等待配置秒数后，调用 store 的 `sync()`。同一个 writer 的周期同步和关闭同步由锁串行化。
3. 调用官方 `dump()`，在内存生成完整快照。开启变化比较时计算 SHA-256，
   与本进程该 writer 最后一次成功提交的摘要比较。每个进程的第一次快照会提交一次。
4. 内容相同且开启比较时直接返回，既不读取目标文件，也不创建 temporary file。
   内容变化或关闭比较时，调用 `storage.atomic_files.write_bytes_atomic()`，
   使用同目录临时文件、flush/fsync 和 `os.replace()` 提交；这条路径关闭重复的磁盘内容比较。
5. 成功提交并完成可选 `mode` 设置后更新内存摘要。失败保留上次成功摘要，
   后台循环记录原始异常并在下个周期重试；其他 store 继续获得同步机会。
6. 官方 shutdown 先停止后台循环，再调用 `close -> sync -> clear`，最后同步待保存变化。
   shutdown 同步失败会向上抛出异常。适配退出时恢复官方方法和间隔。

原子替换前的序列化或写入失败保留已有目标文件，公共 writer 清理本次 temporary file。
本适配只串行化 writer 调用，沿用官方内存 mutation 与序列化的一致性边界；
它不为并发业务 mutation 增加跨资源 transaction。

两个适配实例清空后仍参与同步；其他空的 fallback store 保持上游跳过空字典的行为。

变化比较覆盖嵌套 dict/list 的原地修改、删除及清空，比较依据是官方实际序列化结果。
资源变化时仍写入完整快照。每轮内存序列化与摘要计算的 CPU 开销随快照大小增长，
并短暂持有一份完整序列化字节；本功能减少空闲写盘，不能消除全量序列化成本。
运行记录保留数量由[运行监控设置](user-guide/runtime-observability.md#保留与删除)管理。

## 依赖升级复核

1. 按[LangChain 系依赖升级](langchain-dependency-upgrades.md)进行 scoped 升级，
   比较 API/runtime/CLI 的 release notes 与上表中的实际源码。
2. 如果上游增加正式的 interval/changed-only 配置，优先接入公开配置，删除相应私有适配。
   否则核对全部私有接入点和池生命周期，再更新精确版本门禁与本页基线。
3. 使用项目内置 Python 运行直接行为测试：

   ```powershell
   cd server
   .\.venv\Scripts\python.exe -m pytest ../test/runtime/test_langgraph_dev_persistence.py ../test/security/test_system_settings.py ../test/security/test_launch_settings.py ../test/api_server/test_request_snapshot.py
   ```

4. 使用隔离 data 与随机 loopback 端口启动真实服务，通过公共 Thread API 验证嵌套更新、
   跨周期空闲文件时间/内容不变、关闭比较后周期写入、正常关闭最终保存和重启后的 Thread 读取。
   同时核对官方 SQLite checkpoint/Store 的公共 API 恢复结果；仅在内存构造 fake store 不足以证明接入时机正确。
5. 前端字段或 API projection 改动时运行相关 System Settings 页面测试。
   review 目标 diff、`git diff --check`、文档与版本门禁，确认依赖安装目录保持原样后提交。

官方依据：[CLI dev](https://docs.langchain.com/langsmith/cli#dev)、
[本地开发与测试](https://docs.langchain.com/langsmith/local-dev-testing)、
[本地数据存储](https://docs.langchain.com/langsmith/data-storage-and-privacy#in-memory-development-server)。
