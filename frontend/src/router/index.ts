import { createRouter, createWebHashHistory } from 'vue-router'

const ApiServerSettingsPage = () => import('@/pages/ApiServerSettingsPage.vue')
const ComponentsPage = () => import('@/pages/ComponentsPage.vue')
const ConfigLibraryPage = () => import('@/pages/ConfigLibraryPage.vue')
const ConfigurationRepositoriesPage = () => import('@/pages/ConfigurationRepositoriesPage.vue')
const EventFeedPage = () => import('@/pages/EventFeedPage.vue')
const FileManagerPage = () => import('@/pages/FileManagerPage.vue')
const MainAgentPage = () => import('@/pages/MainAgentPage.vue')
const MessageInterceptionPage = () => import('@/pages/MessageInterceptionPage.vue')
const SystemSettingsPage = () => import('@/pages/SystemSettingsPage.vue')
const SubagentPage = () => import('@/pages/SubagentPage.vue')
const TerminologyPage = () => import('@/pages/TerminologyPage.vue')
const WorkflowsPage = () => import('@/pages/WorkflowsPage.vue')
const WorkflowEditorPage = () => import('@/pages/WorkflowEditorPage.vue')
const WorkflowLifecyclesPage = () => import('@/pages/WorkflowLifecyclesPage.vue')
const ModelMappingPage = () => import('@/pages/ModelMappingPage.vue')
const McpMappingPage = () => import('@/pages/McpMappingPage.vue')

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: ApiServerSettingsPage, meta: { titleKey: 'apiServer.homeTitle' } },
    { path: '/workflows', redirect: '/workflows/parents' },
    { path: '/models', redirect: '/models/connections' },
    { path: '/mcp', redirect: '/mcp/connections' },
    {
      path: '/models/connections',
      component: ComponentsPage,
      props: { scope: 'model' },
      meta: { titleKey: 'navigation.models' },
    },
    { path: '/models/mapping', component: ModelMappingPage, meta: { titleKey: 'navigation.models' } },
    {
      path: '/mcp/connections',
      component: ComponentsPage,
      props: { scope: 'mcp' },
      meta: { titleKey: 'navigation.mcp' },
    },
    { path: '/mcp/mapping', component: McpMappingPage, meta: { titleKey: 'navigation.mcp' } },
    {
      path: '/workflows/parents',
      component: WorkflowsPage,
      props: { workflowRole: 'parent' },
      meta: { titleKey: 'workflows.title' },
    },
    {
      path: '/workflows/children',
      component: WorkflowsPage,
      props: { workflowRole: 'child' },
      meta: { titleKey: 'workflows.title' },
    },
    {
      path: '/system/workflow-lifecycles',
      component: WorkflowLifecyclesPage,
      meta: { titleKey: 'workflowLifecycles.title' },
    },
    {
      path: '/workflows/:id/editor',
      component: WorkflowEditorPage,
      meta: { layout: 'workflow', titleKey: 'workflows.editor.title' },
    },
    { path: '/agents', redirect: '/agents/main' },
    { path: '/agents/main', component: MainAgentPage, meta: { titleKey: 'navigation.agents' } },
    { path: '/agents/subagents', component: SubagentPage, meta: { titleKey: 'navigation.agents' } },
    { path: '/agent-components', component: ComponentsPage, meta: { titleKey: 'components.title' } },
    { path: '/agent-components/:type', component: ComponentsPage, meta: { titleKey: 'components.title' } },
    {
      path: '/workflow-components',
      component: ComponentsPage,
      props: { scope: 'workflow' },
      meta: { titleKey: 'workflowComponents.title' },
    },
    {
      path: '/workflow-components/:type',
      component: ComponentsPage,
      props: { scope: 'workflow' },
      meta: { titleKey: 'workflowComponents.title' },
    },
    { path: '/library', redirect: '/library/configuration-repositories' },
    {
      path: '/library/configuration-repositories',
      component: ConfigurationRepositoriesPage,
      meta: { titleKey: 'configurationRepositories.title' },
    },
    { path: '/library/:type', component: ConfigLibraryPage, meta: { titleKey: 'library.title' } },
    { path: '/system', redirect: '/system/config' },
    {
      path: '/system/config',
      component: SystemSettingsPage,
      meta: { titleKey: 'navigation.system' },
    },
    {
      path: '/files',
      component: FileManagerPage,
      meta: { titleKey: 'navigation.files' },
    },
    {
      path: '/system/message-interception',
      component: MessageInterceptionPage,
      meta: { titleKey: 'navigation.system' },
    },
    { path: '/system/events', component: EventFeedPage, meta: { titleKey: 'navigation.system' } },
    {
      path: '/terminology',
      component: TerminologyPage,
      meta: { titleKey: 'terminology.title' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
