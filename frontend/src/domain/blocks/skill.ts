import {
  cleanName,
  editableText,
  identity,
  overrideValue,
  stringList,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

export interface SkillDraft extends BlockDraftBase {
  skill_package: { folder: string }
  skill_template_paths: string[]
  system_prompt_enabled: boolean
  instruction_override: string
}

interface SkillApiRecord extends BlockDraftBase {
  skill_package?: { folder: string }
  system_prompt_enabled?: boolean
  instruction_override: string | null
}

interface SkillPayload extends BlockPayloadBase {
  skill_package?: { folder: string }
  skill_template_paths?: string[]
  system_prompt_enabled: boolean
  instruction_override: string | null
}

export interface SkillDefaults {
  system_prompt: string
  required_placeholders?: string[]
}

export interface SkillCatalogItem {
  name: string
  folder: string
  template_path: string
  description?: string
}

export const skillAdapter = {
  blank(defaults: SkillDefaults): SkillDraft {
    return {
      id: '', name: '', skill_package: { folder: '' }, skill_template_paths: [],
      system_prompt_enabled: true,
      instruction_override: defaults.system_prompt,
    }
  },
  fromApi(value: SkillApiRecord, defaults: SkillDefaults): SkillDraft {
    return {
      ...identity(value),
      skill_package: {
        folder: typeof value.skill_package?.folder === 'string'
          ? value.skill_package.folder
          : '',
      },
      skill_template_paths: [],
      system_prompt_enabled: value.system_prompt_enabled !== false,
      instruction_override: editableText(value.instruction_override, defaults.system_prompt),
    }
  },
  toPayload(value: SkillDraft, defaults: SkillDefaults): SkillPayload {
    return {
      name: cleanName(value.name),
      ...(value.id
        ? { skill_package: { folder: value.skill_package.folder } }
        : { skill_template_paths: stringList(value.skill_template_paths) }),
      system_prompt_enabled: value.system_prompt_enabled,
      instruction_override: value.system_prompt_enabled
        ? overrideValue(value.instruction_override, defaults.system_prompt)
        : null,
    }
  },
}
