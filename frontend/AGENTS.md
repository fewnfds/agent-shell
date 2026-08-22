# 前端开发入口

`frontend/` 是唯一前端源码。修改本目录时先读取本文件和 `ui-policy.json`；字段、UUID、引用、
权限、路径、保存与运行校验以后端 contract 为权威。

## 按任务读取

- API、payload 或字段映射：读取相关 `api/`、`domain/`、后端 schema 和直接测试。
- 页面、表单、组件、布局、样式或可访问性：读取 `.docs/management-console-ui-contract.md` 的相关章节，
  再按 `ui-patterns/README.md` 索引复用同类 pattern 和参考页。
- 壳层、主题、Modal、Toast、确认或导航：完整读取 UI contract，并核对 `ui-policy.json` 中的受控路径。
- 构建、依赖、运行或发布入口：读取 `../docs/development-and-release.md`。

## 硬边界

- 唯一视觉栈是 Vue 3、AdminLTE 4.1、Bootstrap 5.3、`@adminlte/vue` 和 Bootstrap Icons；
  Workflow editor 只使用已有的 `@vue-flow/core`。禁止引入第二套 UI、Nuxt 或 optional plugin。
- `ui-policy.json` 是组件、class、图标、样式入口和依赖的静态权威；正常复用批准项不需再次审批，
  新视觉能力必须先获得用户批准并更新 policy。
- 页面拥有展示、草稿状态、机械 payload 和请求编排；后端拥有领域、安全和最终校验。
- 不复制后端 schema，不为旧字段增加兼容映射，不用前端判断修补后端错误。
- 自有组件只承载真实产品行为或稳定领域组合；不建立基础控件 wrapper、schema form、页面 builder、
  动态组件 registry 或 Storybook。
- 页面和 editor 不写 `<style>`、内联 `style`、硬编码颜色或 policy 未批准的视觉 class；
  不 patch 或 fork `node_modules`。
- 详细的信息架构、Card、表单、i18n、布局和可访问性规则只维护在 UI contract，
  不在本文件重复或记录局部页面调整。
- 管理端操作统一使用 `action-button`（带图标和通用动作词）或 `icon-action-button`（紧凑位置的纯图标方形按钮）；Vue Flow 画布不适用。

## 验证

完成一批相关修改后，先复核 diff，并按直接风险选择 `npm run ui:check`、`npm run typecheck`、
相关 `npm test -- <file>` 或 `npm run build` 中最接近的一项；不固定串联全部门禁。

除非用户明确要求，否则禁止启动 Debug 服务、打开浏览器或执行浏览器验证。需要真实运行时必须使用
隔离 data 和临时 loopback 端口。
