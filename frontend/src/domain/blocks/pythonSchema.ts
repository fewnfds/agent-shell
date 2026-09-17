import {
  cleanName,
  identity,
  isRecord,
  stringValue,
  type BlockDraftBase,
} from './shared'

export interface PythonSchemaDraft extends BlockDraftBase {
  source: string
}

export interface PythonSchemaPayload {
  name: string
  source: string
}

export const pythonSchemaAdapter = {
  blank(): PythonSchemaDraft {
    return { id: '', name: '', source: '' }
  },
  fromApi(value: unknown): PythonSchemaDraft {
    const source = isRecord(value) ? value : {}
    return {
      ...identity(source),
      source: stringValue(source.source),
    }
  },
  toPayload(value: PythonSchemaDraft): PythonSchemaPayload {
    return {
      name: cleanName(value.name),
      source: value.source,
    }
  },
}
