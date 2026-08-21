# Form field

Find as: 双行字段、纵向 label-input、表单字段、帮助文本、字段错误、form field、label control、help、error。

Use: 一个控件需要统一的 label，以及可选 help/error。Source of truth: `src/components/FormField.vue`；policy: `localComponents.approved[name=FormField]`。

Do not use: Switch/checkbox 自带 Bootstrap label 结构；不要再用裸 `div` 重建已批准字段。

Incorrect: 页面分别手写 `label + control + form-text + invalid-feedback`。

Correct:

```vue
<FormField control-id="timeout" field-path="timeout" :hint="hint" :error="error">
  <template #default="{ describedBy }">
    <input id="timeout" class="form-control" :aria-describedby="describedBy">
  </template>
</FormField>
```

Contract: `control-id` 生成 `<label for>` 及 help/error ID；调用方仍拥有具体控件、值和校验状态。

Verify: `src/pages/SystemSettingsPage.vue`、`src/pages/StyleLabPage.vue`。
