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
  { path: '/mcp', labelKey: 'navigation.mcp', icon: 'bi-plugin' },
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
    prefix: '/mcp',
    items: [
      { path: '/mcp/connections', labelKey: 'navigation.sections.mcpConnections' },
      { path: '/mcp/mapping', labelKey: 'navigation.sections.mcpMapping' },
    ],
  },
  {
    prefix: '/models',
    items: [
      { path: '/models/connections', labelKey: 'navigation.sections.modelConnections' },
      { path: '/models/mapping', labelKey: 'navigation.sections.modelMapping' },
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
      { path: '/agents/async-subagents', labelKey: 'navigation.sections.asyncSubagents' },
    ],
  },
  {
    prefix: '/workflow-components',
    items: [
      {
        path: '/workflow-components/workflow-event-output',
        labelKey: 'navigation.sections.workflowEventOutput',
      },
      {
        path: '/workflow-components/command',
        labelKey: 'navigation.sections.command',
      },
    ],
  },
]

export function sectionNavigationForPath(path: string): SectionNavigationItem[] {
  return sectionNavigationGroups.find((group) => path.startsWith(group.prefix))?.items ?? []
}
