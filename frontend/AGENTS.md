# 前端开发入口

`frontend/` 是唯一前端源码。字段、UUID、引用、权限、路径、保存和运行校验以后端 contract 为权威；前端只拥有展示、草稿状态、机械 payload 与请求编排。

## 首读路径

- API、payload、字段映射：对应 `api/`、`domain/`、后端 schema 与最近的直接测试。
- 页面、表单、布局、样式、文案或可访问性：[管理控制台 UI 契约](../.docs/management-console-ui-contract.md)相关章节，再从 [UI pattern 索引](ui-patterns/README.md)选择一个同类实现。
- 壳层、主题、Modal、Toast 或导航：完整读取 UI contract，并核对 [`ui-policy.json`](ui-policy.json) 的 owner 边界。
- 构建、运行或发布：[开发与发布](../docs/development-and-release.md)。

## 开发范式

- 唯一视觉栈是 Vue 3、AdminLTE 4.1、Bootstrap 5.3、Bootstrap Icons，以及 Workflow editor 使用的 Vue Flow。`ui-policy.json` 只守依赖版本、第二 UI 栈、壳层 import 与共享样式入口，不是 class、图标或组件批准目录。
- 普通配置装配页复用 typed resource definition、`useConfigurationResource` 与现有 layout/action 组件；页面只保留字段、adapter、editor 和领域特有 action。Component/Model editor 的 package inspection、resource catalog、overwrite 与 credential lifecycle 由其专用 controller 承担，同时复用相同 layout/action 范式。没有第二个真实调用方时不提炼通用框架。
- 优先使用 AdminLTE/Bootstrap component、utility 与 theme variable。跨页视觉规则放入 `src/styles/management-console.css`；只属于一个可复用组件的布局可以使用 `<style scoped>`。页面不另造主题，不硬编码颜色，不用 inline style。
- 本地组件只承载真实产品行为或已有调用方共享的稳定组合。不要复制后端 schema、添加旧字段兼容，或用前端校验修补后端错误。
- 管理端操作使用现有 `action-button` 或紧凑位置的 `icon-action-button`；Vue Flow 画布使用自己的紧凑工具范式。
- 前端通常不显式设置长段的说明文字，说明应该留在用户文档中。

## 验证

完成一批相关修改后复核 diff，并按直接风险只选最接近的 `npm run ui:check`、`npm run typecheck`、定向测试或 build；不要固定串联全部命令。

真实运行使用[开发文档](../docs/development-and-release.md#前端-debug)的 `packaging/development/start_dev.ps1`，由它分配隔离 data 和临时 loopback 端口；不得用 `start_server.bat` 启动前端 Debug。
