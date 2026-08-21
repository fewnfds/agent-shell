# 模型

模型连接与配置中的模型要求是两个独立概念。

## 模型连接

在“模型 -> 模型连接”中创建本机可用的 LangChain Provider 连接。这里保存 Provider、服务地址、具体 model、请求参数和凭据；凭据实际值只保存于实例的 env 文件，列表和编辑响应不会回显明文。模型连接是系统私有资源，不会进入 Configuration Repository，也不会被配置 Bundle 导出。

## 模型映射

在“模型 -> 模型映射”中查看当前 Configuration Repository 的全部模型要求。导入配置后，要求默认未绑定；根据要求的 name 与 description 选择本机模型连接并保存。未绑定要求会显示 warning，实际运行前必须完成绑定。

同一个本机模型连接可以绑定多个模型要求。切换 Configuration Repository 后，模型连接列表保持不变，但映射按仓库分别保存。
请求开始装配时会捕获所用 Repository 的 binding、模型连接和 credential 视图。捕获完成后修改或删除连接、解除绑定或切换 Repository，只对后续请求生效。

## 代理组件中的模型要求

“代理组件 -> 模型要求”只编辑可迁移的 name 与多行 description。Main Agent 和 Subagent 引用模型要求 UUID；Provider、endpoint 和 credential
由本机模型连接维护。导出和导入配置时不会携带本机凭据，目标实例可以用自己的模型连接完成映射。
