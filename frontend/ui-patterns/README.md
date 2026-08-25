# UI pattern index

这是前端唯一渐进式范式入口，只负责把需求路由到现有 policy、真实 source 和参考页。

1. 先读取 `../ui-policy.json`，确认依赖栈、共享样式入口和壳层 owner 边界。
2. 按下表或需求词只打开一个匹配的 `.pattern.md` 或布局组合件；命中后复用 source，不重新画近似结构。
3. 没有组合规则时参考同 archetype 页面；只有出现第二个真实调用方时才提炼新的共享 pattern。

| 需求 | Pattern / policy | 参考或验收 |
| --- | --- | --- |
| 纵向字段、label-input、help/error | `form-field.pattern.md` + `FormField.vue` | `src/pages/SystemSettingsPage.vue` |
| 单位输入、毫秒、容量、suffix | `input-with-unit.pattern.md` | `src/pages/SystemSettingsPage.vue` |
| 右侧/行尾/Card header 操作 | `end-aligned-action.pattern.md` | `src/editors/SkillEditor.vue`、`src/components/PythonPackageEditor.vue` |
| 并排表单字段、非 DataTable 搜索/筛选、switch 与 label-input 同排 | `aligned-control-row.pattern.md` | `src/pages/EventFeedPage.vue`、`src/pages/WorkflowsPage.vue` |
| 配置库导航、列表和校验侧栏 | Layout：`ConfigurationLibraryFrame.vue` + `useConfigurationCatalog` | `src/pages/ConfigLibraryPage.vue`、`src/pages/ConfigurationRepositoriesPage.vue` |
| 配置编辑左右工作区、CRUD action dock、复制流程 | Layout：`ConfigurationEditorLayout.vue` + `ConfigurationCrudActions.vue` + `CopyNameModal.vue` | `src/pages/ComponentsPage.vue`、`src/pages/MainAgentPage.vue`、`src/pages/SubagentPage.vue`、`src/pages/WorkflowsPage.vue` |
| 普通表单页 | 无额外 pattern | `src/pages/SystemSettingsPage.vue` |
| 高密度实时页 | 无额外 pattern | `src/pages/EventFeedPage.vue` |
| 复杂配置工作区 | 无额外 pattern | `src/pages/ComponentsPage.vue` 及 `src/editors/` |

`ui-policy.json` 只检查稳定技术边界，UI contract 维护长期原则，真实页面和直接测试负责产品布局与交互验收。
