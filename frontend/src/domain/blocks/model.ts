import {
  cleanName,
  identity,
  isRecord,
  stringValue,
  type BlockDraftBase,
  type BlockPayloadBase,
} from './shared'

type ModelProvider = string
export type ModelProviderSettingInput = string | number | boolean | '' | null
type ModelProviderSettingsDraft = Record<string, ModelProviderSettingInput>

export interface ModelDraft extends BlockDraftBase {
  provider: ModelProvider
  base_url: string
  credential_secret: string
  credential_status: string
  model: string
  provider_settings: ModelProviderSettingsDraft
  tool_choice: string
  response_format: string
  model_settings: string
}

export interface ModelApiRecord extends BlockDraftBase {
  provider?: unknown
  base_url: string
  credential?: { status?: string }
  model: string
  provider_settings?: Record<string, unknown>
  tool_choice?: unknown
  response_format?: unknown
  model_settings?: unknown
}

interface ModelPayload extends BlockPayloadBase {
  provider: ModelProvider
  base_url: string
  credential: string | null
  model: string
  provider_settings: Record<string, unknown>
  tool_choice: unknown
  response_format: unknown
  model_settings: unknown
}

function jsonObjectEditorValue(value: unknown, fallback: string): string {
  return isRecord(value) ? JSON.stringify(value) : fallback
}

function toolChoiceEditorValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'boolean' || isRecord(value)) return JSON.stringify(value)
  return ''
}

function jsonInputValue(value: string, fallback: unknown): unknown {
  if (!value.trim()) return fallback
  try {
    return JSON.parse(value) as unknown
  } catch {
    return value
  }
}

function providerSettingsEditorValue(value: unknown): ModelProviderSettingsDraft {
  if (!isRecord(value)) return {}
  const settings: ModelProviderSettingsDraft = {}
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') {
      settings[key] = item
    } else if (Array.isArray(item) && item.every((entry) => typeof entry === 'string')) {
      settings[key] = JSON.stringify(item)
    }
  }
  return settings
}

function providerSettingsPayload(value: ModelProviderSettingsDraft): Record<string, unknown> {
  const settings: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(value)) {
    if (item === '' || item === null) continue
    settings[key] = (key === 'stop' || key === 'stop_sequences') && typeof item === 'string'
      ? jsonInputValue(item, null)
      : item
  }
  return settings
}

function blankModel(): ModelDraft {
  return {
    id: '', name: '', provider: 'openai', base_url: '', credential_secret: '', credential_status: 'missing', model: '',
    provider_settings: {},
    tool_choice: '', response_format: '', model_settings: '{}',
  }
}

export const modelAdapter = {
  blank: blankModel,
  fromApi(value: ModelApiRecord): ModelDraft {
    const base = identity(value)
    const credential = isRecord(value.credential) ? value.credential : {}
    return {
      ...base,
      provider: stringValue(value.provider, 'openai'),
      base_url: stringValue(value.base_url),
      credential_secret: '',
      credential_status: credential.status === 'masked' ? 'masked' : 'missing',
      model: stringValue(value.model),
      provider_settings: providerSettingsEditorValue(value.provider_settings),
      tool_choice: toolChoiceEditorValue(value.tool_choice),
      response_format: jsonObjectEditorValue(value.response_format, ''),
      model_settings: jsonObjectEditorValue(value.model_settings, '{}'),
    }
  },
  toPayload(value: ModelDraft): ModelPayload {
    return {
      name: cleanName(value.name),
      provider: value.provider,
      base_url: value.base_url.trim(),
      credential: value.credential_secret || null,
      model: value.model.trim(),
      provider_settings: providerSettingsPayload(value.provider_settings),
      tool_choice: jsonInputValue(value.tool_choice, null),
      response_format: jsonInputValue(value.response_format, null),
      model_settings: jsonInputValue(value.model_settings, {}),
    }
  },
}
