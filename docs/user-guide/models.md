# 模型

模型连接与配置中的模型要求是两个独立概念。前后端统一使用 `Model Connection` / `model-connection` contract。

## 模型连接

【配置库 / 全局 / 模型连接】提供模型连接的通用列表，提供查看、编辑、复制和删除，不提供配置下载。编辑动作进入【模型 / 模型连接】，该页面直接复用组件配置编辑框架：选择已有连接后自动载入，底部提供复制、删除、新建和保存，右侧显示服务端校验。

模型连接保存 LangChain Provider、服务地址、具体 model、请求参数和 write-only API Key；凭据实际值只保存于实例 env，列表和编辑响应不会回显明文。它是系统私有资源，不进入 Configuration Repository，也不会被配置 Bundle 或整仓库下载导出。

## 模型映射

在【模型 / 模型映射】中查看当前 Configuration Repository 的全部模型要求。导入配置后，要求默认未绑定；根据要求的 name 与 description 选择模型连接并保存。未绑定要求会显示 warning，实际运行前必须完成绑定。

同一个模型连接可以绑定多个模型要求。切换 Configuration Repository 后，模型连接列表保持不变，但映射按仓库分别保存。
请求开始装配时会捕获所用 Repository 的 binding、Model Connection 和 credential 视图。捕获完成后修改或删除连接、解除绑定或切换 Repository，只对后续请求生效。

## 代理组件中的模型要求

“代理组件 -> 模型要求”只编辑可迁移的 name 与多行 description。Main Agent 和 Subagent 引用模型要求 UUID；Provider、endpoint 和 credential
由本机模型连接维护。导出和导入配置时不会携带本机凭据，目标实例可以用自己的模型连接完成映射。
