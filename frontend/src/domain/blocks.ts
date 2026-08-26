import { customMiddlewareAdapter } from './blocks/customMiddleware'
import { customToolAdapter } from './blocks/customTool'
import { exceptionRetryAdapter } from './blocks/exceptionRetry'
import { filesystemAdapter } from './blocks/filesystem'
import { filesystemToolsAdapter } from './blocks/filesystemTools'
import { modelRequirementAdapter } from './blocks/modelRequirement'
import { agentEventOutputAdapter } from './blocks/agentEventOutput'
import { promptCachingAdapter } from './blocks/promptCaching'
import { skillAdapter } from './blocks/skill'
import { subagentAdapter } from './blocks/subagent'
import { summarizationAdapter } from './blocks/summarization'
import { systemPromptAdapter } from './blocks/systemPrompt'
import { todoListAdapter } from './blocks/todoList'
import { workflowEventOutputAdapter } from './blocks/workflowEventOutput'
import { commandAdapter } from './blocks/command'
import { taskDispatcherAdapter } from './blocks/taskDispatcher'
import { checkpointerAdapter } from './blocks/checkpointer'

export type {
  CustomMiddlewareCatalogItem,
  CustomMiddlewareDraft,
} from './blocks/customMiddleware'
export type {
  CustomToolCatalogItem,
  CustomToolDraft,
} from './blocks/customTool'
export type {
  ExceptionRetryCondition,
  ExceptionRetryDefaults,
  ExceptionRetryDraft,
} from './blocks/exceptionRetry'
export type {
  FilesystemDefaults,
  FilesystemDraft,
  FilesystemImportSource,
  FilesystemBackendType,
  FilesystemPermissionValue,
  FilesystemWorkspace,
  MappedDirectory,
  SkillPackageSummary,
  VirtualSource,
} from './blocks/filesystem'
export type {
  FilesystemToolDefault,
  FilesystemToolsDefaults,
  FilesystemToolsDraft,
} from './blocks/filesystemTools'
export type { ModelRequirementDraft } from './blocks/modelRequirement'
export type { ModelApiRecord, ModelDraft, ModelProviderSettingInput } from './blocks/model'
export { modelAdapter } from './blocks/model'
export type {
  AgentEventOutputCatalogItem,
  AgentEventOutputDraft,
} from './blocks/agentEventOutput'
export type {
  PromptCachingDefaults,
  PromptCachingDraft,
} from './blocks/promptCaching'
export type { BlockDraftBase } from './blocks/shared'
export type { SkillCatalogItem, SkillDefaults, SkillDraft } from './blocks/skill'
export type { SubagentDefaults, SubagentDraft } from './blocks/subagent'
export type {
  SummarizationDefaults,
  SummarizationDraft,
  SummarizationThresholdDraft,
  SummarizationThresholdType,
} from './blocks/summarization'
export type { SystemPromptDraft } from './blocks/systemPrompt'
export type { TodoListDefaults, TodoListDraft } from './blocks/todoList'
export type {
  WorkflowEventOutputCatalogItem,
  WorkflowEventOutputDraft,
} from './blocks/workflowEventOutput'
export type {
  CommandCatalogItem,
  CommandDefaults,
  CommandDraft,
} from './blocks/command'
export type {
  TaskDispatcherCatalogItem,
  TaskDispatcherDefaults,
  TaskDispatcherDraft,
} from './blocks/taskDispatcher'
export type {
  CheckpointDurability,
  CheckpointerDraft,
} from './blocks/checkpointer'

export {
  customMiddlewareAdapter,
  customToolAdapter,
  exceptionRetryAdapter,
  filesystemAdapter,
  filesystemToolsAdapter,
  modelRequirementAdapter,
  agentEventOutputAdapter,
  promptCachingAdapter,
  skillAdapter,
  subagentAdapter,
  summarizationAdapter,
  systemPromptAdapter,
  todoListAdapter,
  workflowEventOutputAdapter,
  commandAdapter,
  taskDispatcherAdapter,
  checkpointerAdapter,
}

export const blockTypes = [
  'model-requirement',
  'custom-tool',
  'custom-middleware',
  'agent-event-output',
  'exception-retry',
  'filesystem',
  'filesystem-tools',
  'skill',
  'system-prompt',
  'subagent',
  'todo-list',
  'summarization',
  'prompt-caching',
] as const

export const managedComponentTypes = [
  ...blockTypes,
  'checkpointer',
  'workflow-event-output',
  'command',
  'task-dispatcher',
] as const

export const blockAdapters = {
  'model-requirement': modelRequirementAdapter,
  'custom-tool': customToolAdapter,
  'custom-middleware': customMiddlewareAdapter,
  'agent-event-output': agentEventOutputAdapter,
  'exception-retry': exceptionRetryAdapter,
  filesystem: filesystemAdapter,
  'filesystem-tools': filesystemToolsAdapter,
  skill: skillAdapter,
  'system-prompt': systemPromptAdapter,
  subagent: subagentAdapter,
  'todo-list': todoListAdapter,
  summarization: summarizationAdapter,
  'prompt-caching': promptCachingAdapter,
  checkpointer: checkpointerAdapter,
  'workflow-event-output': workflowEventOutputAdapter,
  'command': commandAdapter,
  'task-dispatcher': taskDispatcherAdapter,
} as const
