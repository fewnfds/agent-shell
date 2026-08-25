import type { InjectionKey } from 'vue'

import { managementApi } from '@/api'
import type {
  BlockType,
  CapabilityManifest as ApiCapabilityManifest,
  CapabilityOverride as ApiCapabilityOverride,
  CatalogResponse,
  ConfigurationOptions,
  ConfigurationSummary,
  DraftValidationRequest as ApiDraftValidationRequest,
  MainAgent,
  MiddlewareReference as ApiMiddlewareReference,
  ToolReference as ApiToolReference,
  MainAgentPayload as ApiMainAgentPayload,
  Subagent,
  SubagentPayload as ApiSubagentPayload,
  SubagentReference as ApiSubagentReference,
  ValidationReport as ApiValidationReport,
} from '@/api'

export type CapabilityType = BlockType
type OverrideMode = 'inherit' | 'replace' | 'disabled'
type StoredOverrideMode = Exclude<OverrideMode, 'inherit'>

export type CapabilityManifest = ApiCapabilityManifest
type AgentCatalog = CatalogResponse
export type StoredBlock = ConfigurationSummary
export type SubagentReference = ApiSubagentReference
export type MiddlewareReference = ApiMiddlewareReference
export type ToolReference = ApiToolReference

export interface MainAgentProfile extends Omit<MainAgent, 'subagents'> {
  id: string
  subagents: SubagentReference[]
}

type MainAgentPayload = ApiMainAgentPayload
type CapabilityOverride = ApiCapabilityOverride

interface OverrideSelection {
  type: CapabilityType
  mode: OverrideMode
  block_id: string
}

export interface SubagentProfile extends Omit<Subagent, 'settings'> {
  settings: Subagent['settings']
}
type SubagentPayload = ApiSubagentPayload
export type ValidationReport = ApiValidationReport
export type DraftValidationRequest = ApiDraftValidationRequest

export interface AgentAuthoringService {
  getCatalog(): Promise<AgentCatalog>
  getConfigurationOptions(): Promise<ConfigurationOptions>
  getMainAgent(id: string): Promise<MainAgent>
  createMainAgent(payload: MainAgentPayload): Promise<MainAgent>
  updateMainAgent(id: string, payload: MainAgentPayload): Promise<MainAgent>
  copyMainAgent(id: string, name: string): Promise<MainAgent>
  deleteMainAgent(id: string): Promise<{ ok: boolean }>
  getSubagent(id: string): Promise<SubagentProfile>
  createSubagent(payload: SubagentPayload): Promise<SubagentProfile>
  updateSubagent(id: string, payload: SubagentPayload): Promise<SubagentProfile>
  copySubagent(id: string, componentName: string): Promise<SubagentProfile>
  deleteSubagent(id: string): Promise<{ ok: boolean }>
  validateDraft(request: DraftValidationRequest): Promise<ValidationReport>
}

export const agentAuthoringServiceKey: InjectionKey<AgentAuthoringService> = Symbol('agent-authoring-service')

export const managementAgentAuthoringService: AgentAuthoringService = {
  getCatalog: () => managementApi.getCatalog(),
  getConfigurationOptions: () => managementApi.getConfigurationOptions(),
  getMainAgent: (id) => managementApi.getMainAgent(id),
  createMainAgent: (payload) => managementApi.saveMainAgent(payload),
  updateMainAgent: (id, payload) => managementApi.saveMainAgent({ id, ...payload }),
  copyMainAgent: (id, name) => managementApi.copyMainAgent(id, name),
  deleteMainAgent: (id) => managementApi.deleteMainAgent(id),
  getSubagent: (id) => managementApi.getSubagent(id),
  createSubagent: (payload) => managementApi.saveSubagent(payload),
  updateSubagent: (id, payload) => managementApi.saveSubagent({ id, ...payload }),
  copySubagent: (id, componentName) => managementApi.copySubagent(id, componentName),
  deleteSubagent: (id) => managementApi.deleteSubagent(id),
  validateDraft: (request) => managementApi.validateDraft(request),
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

export function blankSubagentReference(): SubagentReference {
  return { subagent_id: '' }
}

export function blankMiddlewareReference(): MiddlewareReference {
  return { middleware_id: '' }
}

export function blankToolReference(): ToolReference {
  return { tool_id: '' }
}

export function normalizeSubagentReference(value: unknown): SubagentReference {
  const source = record(value)
  return { subagent_id: text(source.subagent_id) }
}

export function blankMainAgent(): MainAgentProfile {
  return {
    id: '',
    name: '',
    capability_refs: [],
    tool_refs: [],
    middleware_refs: [],
    subagents: [],
  }
}

export function normalizeMainAgent(value: unknown): MainAgentProfile {
  const source = record(value)
  const references = Array.isArray(source.capability_refs) ? source.capability_refs : []
  const subagents = Array.isArray(source.subagents) ? source.subagents : []
  const toolRefs = Array.isArray(source.tool_refs) ? source.tool_refs : []
  const middlewareRefs = Array.isArray(source.middleware_refs) ? source.middleware_refs : []
  return {
    id: text(source.id),
    name: text(source.name),
    capability_refs: references.map((item) => {
      const reference = record(item)
      return { type: text(reference.type), block_id: text(reference.block_id) }
    }),
    tool_refs: toolRefs.map((item) => {
      const reference = record(item)
      return { tool_id: text(reference.tool_id) }
    }),
    middleware_refs: middlewareRefs.map((item) => {
      const reference = record(item)
      return { middleware_id: text(reference.middleware_id) }
    }),
    subagents: subagents.map(normalizeSubagentReference),
  }
}

export function mainAgentPayload(value: MainAgentProfile): MainAgentPayload {
  return {
    name: value.name.trim(),
    capability_refs: value.capability_refs
      .map((reference) => ({ type: reference.type, block_id: reference.block_id })),
    tool_refs: value.tool_refs.map((reference) => ({
      tool_id: reference.tool_id,
    })),
    middleware_refs: value.middleware_refs.map((reference) => ({
      middleware_id: reference.middleware_id,
    })),
    subagents: value.subagents.map((reference) => ({
      subagent_id: reference.subagent_id,
    })),
  }
}

export function referenceId(value: MainAgentProfile, type: CapabilityType): string {
  return value.capability_refs.find((item) => item.type === type)?.block_id ?? ''
}

export function setReference(value: MainAgentProfile, type: CapabilityType, blockId: string): void {
  value.capability_refs = value.capability_refs.filter((item) => item.type !== type)
  if (blockId) value.capability_refs.push({ type, block_id: blockId })
}

export function blankSubagent(): SubagentProfile {
  return {
    id: '',
    component_name: '',
    name: '',
    description: '',
    settings: {
      capability_overrides: [],
      tool_refs: [],
      middleware_refs: [],
    },
  }
}

export function normalizeSubagent(value: unknown): SubagentProfile {
  const source = record(value)
  const settings = record(source.settings)
  const overrides = Array.isArray(settings.capability_overrides)
    ? settings.capability_overrides
    : []
  const middlewareRefs = Array.isArray(settings.middleware_refs)
    ? settings.middleware_refs
    : []
  const toolRefs = Array.isArray(settings.tool_refs)
    ? settings.tool_refs
    : []
  return {
    id: text(source.id),
    component_name: text(source.component_name),
    name: text(source.name),
    description: text(source.description),
    settings: {
      capability_overrides: overrides.map((item): CapabilityOverride => {
        const override = record(item)
        return {
          type: text(override.type),
          mode: text(override.mode) as StoredOverrideMode,
          block_id: text(override.block_id),
        }
      }),
      tool_refs: toolRefs.map((item) => {
        const reference = record(item)
        return { tool_id: text(reference.tool_id) }
      }),
      middleware_refs: middlewareRefs.map((item) => {
        const reference = record(item)
        return { middleware_id: text(reference.middleware_id) }
      }),
    },
  }
}

export function overrideSelection(value: SubagentProfile, type: CapabilityType): OverrideSelection {
  return value.settings.capability_overrides.find((item) => item.type === type)
    ?? { type, mode: 'inherit', block_id: '' }
}

export function setOverrideSelection(
  value: SubagentProfile,
  type: CapabilityType,
  mode: OverrideMode,
  blockId = '',
): void {
  value.settings.capability_overrides = value.settings.capability_overrides
    .filter((item) => item.type !== type)
  if (mode !== 'inherit') {
    value.settings.capability_overrides.push({
      type,
      mode,
      block_id: mode === 'replace' ? blockId : '',
    })
  }
}

export function subagentPayload(value: SubagentProfile): SubagentPayload {
  return {
    component_name: value.component_name.trim(),
    name: value.name.trim(),
    description: value.description,
    settings: {
      capability_overrides: value.settings.capability_overrides
        .map((selection) => ({ ...selection })),
      tool_refs: value.settings.tool_refs.map((reference) => ({
        tool_id: reference.tool_id,
      })),
      middleware_refs: value.settings.middleware_refs.map((reference) => ({
        middleware_id: reference.middleware_id,
      })),
    },
  }
}
