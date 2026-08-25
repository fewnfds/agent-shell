# Form field

Find as: 双行字段、纵向 label-input、表单字段、帮助文本、字段错误、form field、label control、help、error。

Use: 一个控件需要按 payload path 解析的统一 label，以及可选 help/error。Source of truth: `src/components/FormField.vue`。单位输入见 `input-with-unit.pattern.md`，并排字段见 `aligned-control-row.pattern.md`。

Do not use: Switch/checkbox 使用 Bootstrap `form-switch`，不包裹 FormField；`LteInput`/`LteTextarea` 已通过 `label` prop 提供标签时不叠加 FormField。不要再用裸 `div` 重建已批准字段。

Incorrect: 页面分别手写 `label + control + form-text + invalid-feedback`。

Correct:

```vue
<FormField control-id="name" field-path="name" :hint="'Visible configuration name.'" :error="error">
  <template #default="{ describedBy, invalid }">
    <input id="name" class="form-control" :class="{ 'is-invalid': invalid }" :aria-describedby="describedBy" :aria-invalid="invalid">
  </template>
</FormField>
```

Contract: `field-path` 必传并通过 field label catalog 与 i18n 决定 label，`label-key` 可覆盖；`technical` 或 debug locale 显示原始 key/path。`control-id` 可选，存在时才渲染 `<label for>`，并在对应 hint/error 存在时生成 help/error ID；缺省时 label 为 `<span>`，`describedBy` 为 `undefined`。slot 还提供 `invalid`，调用方负责绑定控件值、`aria-invalid` 与 `is-invalid`。与单位 ID 同时使用时，调用方需把 `describedBy` 和 `<control-id>-unit` 合并。

Reference / Verify: `src/pages/SystemSettingsPage.vue`、`src/editors/FilesystemEditor.vue`、`src/components/RecordPicker.vue`。路径相对于 `frontend/`。
