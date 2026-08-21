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

私有包根的直接子目录是 Skill；它与 Template 完全解耦，用户或 AI 可以直接编辑。已存在同名 Skill 时 Add 返回冲突且不覆盖，必须先从右侧删除或手动删除目录并点击 Refresh。组件页载入或刷新时才扫描私有包并显示 warning；warning 不阻塞保存、装配、仓库切换、Bundle 或进程退出。Runtime 将最终私有包映射到官方 `/skills/` namespace，并保持只读隔离。
