# Skill

公共 Skill Template 根为 `data/skills-template/`。扫描允许任意层级；某一层第一次发现 `SKILL.md` 后，该目录就是完整 Skill 边界，合法或不合法都不再递归。只有名称、目录、UTF-8 和 YAML frontmatter 通过当前 contract 的 Template 才能在前端选择，catalog 同时按规范相对路径报告坏项。

创建请求使用 Template 路径，服务端复制完整目录到 Component owner UUID 的私有包：

```json
{
  "name": "写作技能",
  "skill_template_paths": ["writing/outline", "review/continuity-check"],
  "system_prompt_enabled": true,
  "instruction_override": null
}
```

保存后的记录只引用：

```json
{"skill_package": {"folder": "<component-uuid>"}}
```

新建组件时使用 `skill_template_paths`，系统复制所选 Template 后只保存 `skill_package`。已有组件的普通更新必须继续提交原 `skill_package` 引用；增量添加使用 `POST /api/blocks/skill/{id}/skills` 与 `{"template_path": "..."}`，删除使用 `DELETE /api/blocks/skill/{id}/skills/{folder_name}`。

`system_prompt_enabled: false` 时，`instruction_override` 必须为 `null`。启用且提供 override 时，文本最多 100,000 字符，并必须各包含一次或多次 `{skills_locations}`、`{skills_load_warnings}` 和 `{skills_list}`；不支持其他 placeholder、conversion 或 format spec。

私有包根的直接子目录是 Skill；它与 Template 完全解耦，用户或 AI 可以直接编辑。已存在同名 Skill 时 Add 返回冲突且不覆盖，必须先从右侧删除或手动删除目录并点击 Refresh。组件页载入或刷新时才扫描私有包并显示 warning；warning 不阻塞保存、装配、仓库切换、Bundle 或进程退出。Runtime 将当前 Agent 选择的私有 Skill 映射到官方只读 `/skills/` namespace。
