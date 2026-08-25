# End-aligned action

Find as: 右侧操作、靠右按钮、标题栏操作、行尾操作、right action、end action、card header action。

Use: Card header 或普通行有一个明确的末端操作。Source of truth: Bootstrap flex + 直接 flex item 的 `ms-auto`。

Do not use: 不得仅靠 `justify-content-between` 推断末端位置；需显式使用 `ms-auto`，也不假设 AdminLTE 会把 class 转发到最终节点。

Correct:

```vue
<header class="card-header d-flex align-items-center gap-2">
  <h2 class="card-title">Title</h2>
  <LteButton class="icon-action-button ms-auto" aria-label="Add" title="Add" type="button">
    <i class="bi bi-plus-lg" aria-hidden="true" />
  </LteButton>
</header>
```

Contract: 单个操作的 `ms-auto` 位于最终按钮，多个操作则位于包裹按钮组的直接 flex item；验收最终 DOM，确保该元素是父 flex 容器的直接子项。验收目标是贴近容器末端，不是右侧区域内居中。

Reference / Verify: `src/editors/SkillEditor.vue`、`src/components/PythonPackageEditor.vue`。路径相对于 `frontend/`。
