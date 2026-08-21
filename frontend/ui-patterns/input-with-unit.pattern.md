# Input with unit

Find as: 单位输入、毫秒、秒、容量、长度、input unit、suffix、addon、ms、MiB。

Use: 数值含义需要声明单位。Source of truth: Bootstrap `input-group` + 末端 `input-group-text`；policy: `styles.classRecipes[name=forms-and-actions]`。

Do not use: 不把单位写进标题、label 括号、备注、tooltip 或 placeholder。

Incorrect: `配置报警间隔（毫秒）` 加一个普通输入框。

Correct:

```vue
<div class="input-group">
  <input aria-describedby="interval-unit" class="form-control" type="number">
  <span id="interval-unit" class="input-group-text">ms</span>
</div>
```

Contract: 单位可见、紧邻输入框，并通过 `aria-describedby` 关联。

Verify: `src/pages/SystemSettingsPage.vue`、`src/pages/StyleLabPage.vue`。
