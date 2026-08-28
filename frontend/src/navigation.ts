interface NavigationItem {
  path: string
  labelKey: string
  icon: string
}

export const navigationItems: NavigationItem[] = [
  { path: '/', labelKey: 'navigation.home', icon: 'bi-house' },
  { path: '/system', labelKey: 'navigation.system', icon: 'bi-gear' },
  { path: '/files', labelKey: 'navigation.files', icon: 'bi-folder' },
  { path: '/models', labelKey: 'navigation.models', icon: 'bi-robot' },
  { path: '/agents', labelKey: 'navigation.agents', icon: 'bi-robot' },
  { path: '/agent-components', labelKey: 'navigation.components', icon: 'bi-boxes' },
  { path: '/workflows', labelKey: 'navigation.workflows', icon: 'bi-diagram-3' },
  {
    path: '/workflow-components',
    labelKey: 'navigation.workflowComponents',
    icon: 'bi-node-plus',
  },
  { path: '/library', labelKey: 'navigation.library', icon: 'bi-archive' },
  { path: '/terminology', labelKey: 'navigation.terminology', icon: 'bi-book' },
]

interface SectionNavigationItem {
  path: string
  labelKey: string
}

interface SectionNavigationGroup {
  prefix: string
  items: SectionNavigationItem[]
}

const sectionNavigationGroups: SectionNavigationGroup[] = [
  {
    prefix: '/models',
    items: [
      { path: '/models/connections', labelKey: 'navigation.sections.modelConnections' },
      { path: '/models/mapping', labelKey: 'navigation.sections.modelMapping' },
    ],
  },
  {
    prefix: '/workflows',
    items: [
      { path: '/workflows/parents', labelKey: 'navigation.sections.parentWorkflows' },
      { path: '/workflows/children', labelKey: 'navigation.sections.childWorkflows' },
    ],
  },
  {
    prefix: '/system',
    items: [
      { path: '/system/config', labelKey: 'navigation.sections.systemSettings' },
      {
        path: '/system/message-interception',
        labelKey: 'navigation.sections.messageInterception',
      },
      { path: '/system/events', labelKey: 'navigation.sections.eventFeed' },
      { path: '/system/workflow-lifecycles', labelKey: 'navigation.sections.workflowLifecycles' },
    ],
  },
  {
    prefix: '/agents',
    items: [
      { path: '/agents/main', labelKey: 'navigation.sections.mainAgent' },
      { path: '/agents/subagents', labelKey: 'navigation.sections.subagents' },
    ],
  },
  {
    prefix: '/workflow-components',
    items: [
      {
        path: '/workflow-components/checkpointer',
        labelKey: 'navigation.sections.checkpointer',
      },
      {
        path: '/workflow-components/workflow-event-output',
        labelKey: 'navigation.sections.workflowEventOutput',
      },
      {
        path: '/workflow-components/response-stream-scheduling',
        labelKey: 'navigation.sections.responseStreamScheduling',
      },
      {
        path: '/workflow-components/command',
        labelKey: 'navigation.sections.command',
      },
      {
        path: '/workflow-components/task-dispatcher',
        labelKey: 'navigation.sections.taskDispatcher',
      },
    ],
  },
]

export function sectionNavigationForPath(path: string): SectionNavigationItem[] {
  return sectionNavigationGroups.find((group) => path.startsWith(group.prefix))?.items ?? []
}
