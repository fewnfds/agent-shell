# End-aligned action

Find as: 右侧操作、靠右按钮、标题栏操作、行尾操作、right action、end action、card header action。

Use: Card header 或普通行有一个明确的末端操作。Source of truth: Bootstrap flex + 直接 flex item 的 `ms-auto`；policy: `styles.classRecipes[name=approved-utilities]`。

Do not use: 不仅靠 `justify-content-between`；不假设 AdminLTE 会把 class 转发到最终节点。

Correct:

```vue
<header class="card-header d-flex align-items-center gap-2">
  <h2 class="card-title">Title</h2>
  <button class="btn btn-secondary btn-sm ms-auto" type="button">Action</button>
</header>
```

Contract: `ms-auto` 必须位于最终 DOM 的直接 flex item；验收目标是贴近容器末端，不是右侧区域内居中。

Verify: `src/pages/StyleBaselinePage.vue`。
