# UI pattern index

这是前端唯一渐进式范式入口，只负责把需求路由到现有 policy、真实 source 和参考页。

1. 先读取 `../ui-policy.json` 中命中条目的组件、class 和图标边界。
2. 按下表或需求词只打开一个匹配的 `.pattern.md` 或布局组合件；命中后复用 source，不重新画近似结构。
3. 没有组合规则时只参考同 archetype 页面；仍无匹配项则申请批准，不自动新增 pattern。

| 需求 | Pattern / policy | 参考或验收 |
| --- | --- | --- |
| 纵向字段、label-input、help/error | `form-field.pattern.md`；`localComponents.approved[name=FormField]` | `src/pages/SystemSettingsPage.vue` |
| 单位输入、毫秒、容量、suffix | `input-with-unit.pattern.md`；`styles.classRecipes[name=forms-and-actions]` | `src/pages/SystemSettingsPage.vue` |
| 右侧/行尾/Card header 操作 | `end-aligned-action.pattern.md`；`approved-utilities` + `content-and-data` + `forms-and-actions` | `src/editors/SkillEditor.vue`、`src/components/PythonPackageEditor.vue` |
| 并排表单字段、非 DataTable 搜索/筛选、switch 与 label-input 同排 | `aligned-control-row.pattern.md`；`forms-and-actions` + `approved-utilities` | `src/pages/StyleBaselinePage.vue`、`src/pages/EventFeedPage.vue`、`src/pages/WorkflowsPage.vue` |
| 配置库导航、列表和校验侧栏 | Layout：`ConfigurationLibraryFrame.vue` + `useConfigurationCatalog` | `src/pages/ConfigLibraryPage.vue`、`src/pages/ConfigurationRepositoriesPage.vue` |
| 配置编辑左右工作区、CRUD action dock、复制流程 | Layout：`ConfigurationEditorLayout.vue` + `ConfigurationCrudActions.vue` + `CopyNameModal.vue` | `src/pages/ComponentsPage.vue`、`src/pages/MainAgentPage.vue`、`src/pages/SubagentPage.vue`、`src/pages/WorkflowsPage.vue` |
| 普通表单页 | 无额外 pattern | `src/pages/SystemSettingsPage.vue` |
| 高密度实时页 | 无额外 pattern | `src/pages/EventFeedPage.vue` |
| 复杂配置工作区 | 无额外 pattern | `src/pages/ComponentsPage.vue` 及 `src/editors/` |

`ui-policy.json` 是机器门禁，Style Baseline 是真实渲染验收面，UI contract 是长期原则；它们都不另行定义检索流程。
