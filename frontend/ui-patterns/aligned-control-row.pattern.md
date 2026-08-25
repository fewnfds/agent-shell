# Aligned control row

Find as: 并排表单字段、非 DataTable 搜索/筛选工具栏、switch 与 label-input 同排、control row。DataTable 搜索和筛选使用 `DataTableWorkbench` 自己的 `collection-filter-*` 布局。

Use: 直接复用 AdminLTE/Bootstrap 现成结构，不增加项目级布局 class。

Contract:

- 普通字段使用 `.form-label` + `.form-control` / `.form-select`；需要字段语义、help 或 error 时使用 `FormField`。
- 单位或同行动作使用 `.input-group`；开关使用 `.form-check.form-switch`。
- 同一父级下不要直接堆叠多个 Bootstrap `.row`；把可换行的列放进同一个 row，避免 gutter 的负顶部间距与组件自身的 `mb-3` 偶然互相抵消。
- 真实表单中 switch 与 label-input 并排时使用 `row g-3`、列 class 和 `data-ui-control-row`；每列提供 `.form-label`、`FormField` 或自带 label 的框架控件，switch 列标题也遵循同一可见标签语义。
- switch 列标题已完整表达含义、内部 label 只是重复文案时，内部 label 使用 `.visually-hidden`；内部 label 承载独立语义时保留可见 `.form-check-label`。禁止把无标题 switch 居中塞进 label-input 行。
- `list-group-item` 等重复列表行、卡片/分组标题和独立 switch 不使用本范式，不为对齐额外补 `.form-label`。
- 控件保持组件默认宽高。禁止为统一外观增加固定高度、最小行高、等高 grid、slot flex wrapper 或页面私有尺寸补丁。
- `btn-sm` 只用于现有表格/列表行与 DataTable 紧凑选项；普通搜索、提交和表单动作沿用参考源码中的尺寸。

Reference: `src/pages/EventFeedPage.vue`、`src/pages/WorkflowsPage.vue`。路径相对于 `frontend/`。
