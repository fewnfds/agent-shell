import type { McpReference } from '@/api'

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

export function blankMcpReference(): McpReference {
  return {
    requirement_id: '',
    tool_selection: { mode: 'all', tools: [] },
  }
}

export function normalizeMcpReference(value: unknown): McpReference {
  const source = record(value)
  const selection = record(source.tool_selection)
  const mode = selection.mode === 'include' ? 'include' : 'all'
  return {
    requirement_id: text(source.requirement_id),
    tool_selection: {
      mode,
      tools: mode === 'include' && Array.isArray(selection.tools)
        ? selection.tools.map(text)
        : [],
    },
  }
}

export function mcpReferencePayload(value: McpReference): McpReference {
  return {
    requirement_id: value.requirement_id,
    tool_selection: {
      mode: value.tool_selection.mode,
      tools: value.tool_selection.mode === 'include'
        ? value.tool_selection.tools.map((name) => name.trim())
        : [],
    },
  }
}
