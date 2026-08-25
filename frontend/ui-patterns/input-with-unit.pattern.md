# Input with unit

Find as: 单位输入、毫秒、秒、容量、长度、input unit、suffix、addon、ms、MiB。

Use: 数值含义需要声明单位。Source of truth: Bootstrap `input-group` + 末端 `input-group-text`。

Do not use: 不把单位写进标题、label 括号、备注、tooltip 或 placeholder。

Incorrect: `配置报警间隔（毫秒）` 加一个普通输入框。

Correct:

```vue
<FormField control-id="configuration-validation-debounce" field-path="debounce_ms">
  <div class="input-group">
    <input id="configuration-validation-debounce" aria-describedby="configuration-validation-debounce-unit" class="form-control" type="number">
    <span id="configuration-validation-debounce-unit" class="input-group-text">ms</span>
  </div>
</FormField>
```

Contract: 单一单位后缀可见且紧邻输入框末端，使用页面唯一的 `<control-id>-unit` ID，并通过 `aria-describedby` 关联；控件仍须通过 FormField 或原生 label 获得可访问名称。若 FormField 同时提供 hint/error，将 slot 的 `describedBy` 与单位 ID 合并。单位优先使用 i18n 文案，`ms`、`MiB`、`s` 等通用缩写可保持统一字面量。

Reference / Verify: `src/pages/SystemSettingsPage.vue`、`src/editors/FilesystemEditor.vue`、`src/editors/SummarizationEditor.vue`。路径相对于 `frontend/`。
