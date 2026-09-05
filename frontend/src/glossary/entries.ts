import type { GlossaryEntry, GlossarySource } from './types'

const SOURCES: Record<string, GlossarySource> = {
    agents: { label: 'LangChain Agents', url: 'https://docs.langchain.com/oss/python/langchain/agents' },
    models: { label: 'LangChain Models', url: 'https://docs.langchain.com/oss/python/langchain/models' },
    messages: { label: 'LangChain Messages', url: 'https://docs.langchain.com/oss/python/langchain/messages' },
    tools: { label: 'LangChain Tools', url: 'https://docs.langchain.com/oss/python/langchain/tools' },
    middleware: { label: 'LangChain Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/overview' },
    middlewareHooks: { label: 'LangChain Middleware Hooks', url: 'https://docs.langchain.com/oss/python/langchain/middleware/custom#hooks' },
    middlewareWrapHooks: { label: 'LangChain Wrap-style Hooks', url: 'https://docs.langchain.com/oss/python/langchain/middleware/custom#wrap-style-hooks' },
    middlewareOrder: { label: 'LangChain Middleware Execution Order', url: 'https://docs.langchain.com/oss/python/langchain/middleware/custom#execution-order' },
    structured: { label: 'LangChain Structured Output', url: 'https://docs.langchain.com/oss/python/langchain/structured-output' },
    streaming: { label: 'LangChain Streaming', url: 'https://docs.langchain.com/oss/python/langchain/streaming' },
    streamModes: { label: 'LangChain Supported Stream Modes', url: 'https://docs.langchain.com/oss/python/langchain/streaming#supported-stream-modes' },
    agentInvocation: { label: 'LangChain Agent Invocation', url: 'https://docs.langchain.com/oss/python/langchain/agents#invocation' },
    retrieval: { label: 'LangChain Retrieval', url: 'https://docs.langchain.com/oss/python/langchain/retrieval' },
    shortMemory: { label: 'LangChain Short Term Memory', url: 'https://docs.langchain.com/oss/python/langchain/short-term-memory' },
    longMemory: { label: 'LangChain Long Term Memory', url: 'https://docs.langchain.com/oss/python/langchain/long-term-memory' },
    multiAgent: { label: 'LangChain Multi Agent', url: 'https://docs.langchain.com/oss/python/langchain/multi-agent' },
    context: { label: 'LangChain Context Engineering', url: 'https://docs.langchain.com/oss/python/langchain/context-engineering' },
    mcp: { label: 'LangChain MCP', url: 'https://docs.langchain.com/oss/python/langchain/mcp' },
    deepagents: { label: 'Deep Agents Overview', url: 'https://docs.langchain.com/oss/python/deepagents/overview' },
    deepBackends: { label: 'Deep Agents Backends', url: 'https://docs.langchain.com/oss/python/deepagents/backends' },
    deepSkills: { label: 'Deep Agents Skills', url: 'https://docs.langchain.com/oss/python/deepagents/skills' },
    deepSubagents: { label: 'Deep Agents Subagents', url: 'https://docs.langchain.com/oss/python/deepagents/subagents' },
    compiledSubagentApi: { label: 'Deep Agents CompiledSubAgent API', url: 'https://reference.langchain.com/python/deepagents/middleware/subagents/CompiledSubAgent' },
    subagentExecution: { label: 'LangChain Synchronous and Asynchronous Subagents', url: 'https://docs.langchain.com/oss/python/langchain/multi-agent/subagents#sync-vs-async' },
    indirectPromptInjection: { label: 'Deep Agents RAG Security Considerations', url: 'https://docs.langchain.com/oss/python/deepagents/rag#security-considerations' },
    deepCustomization: { label: 'Deep Agents Customization', url: 'https://docs.langchain.com/oss/python/deepagents/customization#customize-the-task-tool-description' },
    deepFilesystem: { label: 'Deep Agents FilesystemMiddleware API', url: 'https://reference.langchain.com/python/deepagents/middleware/filesystem/FilesystemMiddleware' },
    deepSkillsApi: { label: 'Deep Agents SkillsMiddleware API', url: 'https://reference.langchain.com/python/deepagents/middleware/skills/SkillsMiddleware' },
    agentFactory: { label: 'LangChain create_agent API', url: 'https://reference.langchain.com/python/langchain/agents/factory/create_agent' },
    customMiddleware: { label: 'LangChain Custom Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/custom#class-based-middleware' },
    modelRequestApi: { label: 'LangChain ModelRequest API', url: 'https://reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest' },
    modelResponseApi: { label: 'LangChain ModelResponse API', url: 'https://reference.langchain.com/python/langchain/agents/middleware/types/ModelResponse' },
    wrapModelCallApi: { label: 'LangChain wrap_model_call API', url: 'https://reference.langchain.com/python/langchain/agents/middleware/types/wrap_model_call' },
    baseMessageApi: { label: 'LangChain BaseMessage API', url: 'https://reference.langchain.com/python/langchain-core/messages/base/BaseMessage' },
    runnableApi: { label: 'LangChain Runnable API', url: 'https://reference.langchain.com/python/langchain-core/runnables/base/Runnable' },
    dynamicPromptMiddleware: { label: 'LangChain Dynamic Prompt Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/custom#dynamic-prompt' },
    toolDefinition: { label: 'LangChain Tool Definition', url: 'https://docs.langchain.com/oss/python/langchain/tools#basic-tool-definition' },
    baseTool: { label: 'LangChain BaseTool API', url: 'https://reference.langchain.com/python/langchain-core/tools/base/BaseTool' },
    todoMiddleware: { label: 'LangChain To-do List Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/built-in#to-do-list' },
    todoMiddlewareApi: { label: 'LangChain TodoListMiddleware API', url: 'https://reference.langchain.com/python/langchain/agents/middleware/todo/TodoListMiddleware' },
    modelRetryMiddleware: { label: 'LangChain Model Retry Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/built-in#model-retry' },
    retryMiddleware: { label: 'LangChain Retry Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/built-in#tool-retry' },
    piiMiddleware: { label: 'LangChain PII Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/built-in#pii-detection' },
    callLimitMiddleware: { label: 'LangChain Call Limit Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/built-in#tool-call-limit' },
    toolSelectorMiddleware: { label: 'LangChain LLM Tool Selector Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/built-in#llm-tool-selector' },
    contextEditingMiddleware: { label: 'LangChain Context Editing Middleware', url: 'https://docs.langchain.com/oss/python/langchain/middleware/built-in#context-editing' },
    chatOpenAI: { label: 'LangChain ChatOpenAI', url: 'https://docs.langchain.com/oss/python/integrations/chat/openai' },
    subagentMiddlewareApi: { label: 'Deep Agents SubAgentMiddleware API', url: 'https://reference.langchain.com/python/deepagents/middleware/subagents/SubAgentMiddleware' },
    openaiOverview: { label: 'OpenAI API Overview', url: 'https://developers.openai.com/api/reference/overview' },
    openaiChat: { label: 'OpenAI Chat Completions API', url: 'https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create' },
    openaiChatStreaming: { label: 'OpenAI Chat Completions Streaming Events', url: 'https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events' },
    openaiModels: { label: 'OpenAI Models API', url: 'https://developers.openai.com/api/reference/resources/models/methods/list' },
    openaiErrors: { label: 'OpenAI API Error Codes', url: 'https://developers.openai.com/api/docs/guides/error-codes' },
    openaiOpenApi: { label: 'OpenAI OpenAPI Specification', url: 'https://github.com/openai/openai-openapi/blob/main/openapi.yaml' },
    langgraph: { label: 'LangGraph Overview', url: 'https://docs.langchain.com/oss/python/langgraph/overview' },
    persistence: { label: 'LangGraph Persistence', url: 'https://docs.langchain.com/oss/python/langgraph/persistence' },
    interrupts: { label: 'LangGraph Interrupts', url: 'https://docs.langchain.com/oss/python/langgraph/interrupts' },
    graphRecursion: { label: 'LangGraph Recursion Limit', url: 'https://docs.langchain.com/oss/python/langgraph/use-graph-api#impose-a-recursion-limit' },
    guardrails: { label: 'LangChain Guardrails', url: 'https://docs.langchain.com/oss/python/langchain/guardrails' },
    llm: { label: 'Wikipedia: Large language model', url: 'https://en.wikipedia.org/wiki/Large_language_model' },
    transformer: { label: 'Wikipedia: Transformer', url: 'https://en.wikipedia.org/wiki/Transformer_(deep_learning_architecture)' },
    nlp: { label: 'Wikipedia: Natural language processing', url: 'https://en.wikipedia.org/wiki/Natural_language_processing' },
    ml: { label: 'Wikipedia: Machine learning', url: 'https://en.wikipedia.org/wiki/Machine_learning' },
    generative: { label: 'Wikipedia: Generative artificial intelligence', url: 'https://en.wikipedia.org/wiki/Generative_artificial_intelligence' },
    prompt: { label: 'Wikipedia: Prompt engineering', url: 'https://en.wikipedia.org/wiki/Prompt_engineering' },
    rag: { label: 'Wikipedia: Retrieval augmented generation', url: 'https://en.wikipedia.org/wiki/Retrieval-augmented_generation' },
    vector: { label: 'Wikipedia: Vector database', url: 'https://en.wikipedia.org/wiki/Vector_database' },
    search: { label: 'Wikipedia: Information retrieval', url: 'https://en.wikipedia.org/wiki/Information_retrieval' },
    multiagentWiki: { label: 'Wikipedia: Multi agent system', url: 'https://en.wikipedia.org/wiki/Multi-agent_system' },
    xai: { label: 'Wikipedia: Explainable artificial intelligence', url: 'https://en.wikipedia.org/wiki/Explainable_artificial_intelligence' },
    aiSafety: { label: 'Wikipedia: AI safety', url: 'https://en.wikipedia.org/wiki/AI_safety' },
    aiAlignment: { label: 'Wikipedia: AI alignment', url: 'https://en.wikipedia.org/wiki/AI_alignment' },
    owaspPromptInjection: { label: 'OWASP Prompt Injection Prevention', url: 'https://cheatsheetseries.owasp.org/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.html' },
    agentShellSystemManagement: { label: 'Agent Shell: Data and system management', url: 'https://github.com/fewnfds/agent-shell/blob/dev/docs/user-guide/system-management.md' },
    hallucination: { label: 'Wikipedia: Hallucination', url: 'https://en.wikipedia.org/wiki/Hallucination_(artificial_intelligence)' },
    benchmark: { label: 'Wikipedia: Benchmark', url: 'https://en.wikipedia.org/wiki/Benchmark_(computing)' },
    reinforcement: { label: 'Wikipedia: Reinforcement learning', url: 'https://en.wikipedia.org/wiki/Reinforcement_learning' },
  }

function sourceFor(key: string): GlossarySource {
  const source = SOURCES[key]
  if (!source) throw new Error(`Unknown glossary source: ${key}`)
  return source
}

const entries: GlossaryEntry[] = []

function variantsFor(english: string, variants: readonly string[] = []): string[] {
  const lower = english.toLowerCase()
  const generated = [lower]
  if (/^[a-z0-9]+(?:[ -]+[a-z0-9]+)*$/.test(lower)) {
    const words = lower.split(/[ -]+/)
    generated.push(words.join('_'), words.join('-'), words.join(''))
  }
  return Array.from(new Set([...generated, ...variants]))
}

function term(
  source: string,
  key: string,
  english: string,
  zh: string,
  descriptionZh: string,
  descriptionEn: string,
  variants: readonly string[] = [],
): void {
  entries.push({
    key,
    english,
    variants: variantsFor(english, variants),
    zh,
    descriptionZh,
    descriptionEn,
    sources: [sourceFor(source)],
    scope: 'ai-agent-concept',
  })
}

function technologyTerm(
  source: string,
  key: string,
  english: string,
  zh: string,
  descriptionZh: string,
  descriptionEn: string,
  variants: readonly string[] = [],
): void {
  entries.push({
    key,
    english,
    variants: variantsFor(english, variants),
    zh,
    descriptionZh,
    descriptionEn,
    sources: [sourceFor(source)],
    scope: 'project-technology',
  })
}

  term('agents', 'agent', 'Agent', '智能体', '以目标为导向，利用模型推理并可调用工具采取行动的计算系统。', 'A goal-directed computational system that uses model reasoning and may call tools to take actions.');
  term('agents', 'agent-loop', 'Agent Loop', '智能体循环', '在观察、推理、行动和反馈之间反复迭代的执行过程。', 'An execution process that iterates through observation, reasoning, action, and feedback.');
  term('agents', 'agent-run', 'Agent Run', '智能体运行', '智能体从接收输入到结束或暂停的一次完整执行实例。', 'One complete execution instance of an agent from input until completion or suspension.');
  term('agentInvocation', 'agent-invocation', 'Agent Invocation', '智能体调用', '通过调用接口向智能体提交输入、从而启动或继续一次执行的调用行为。', 'The act of submitting input through an agent invocation interface to start or continue an execution.');
  term('agents', 'agent-state', 'Agent State', '智能体状态', '智能体运行期间由多个步骤共享和更新的数据集合。', 'The collection of data shared and updated across steps during an agent run.');
  term('agents', 'agent-step', 'Agent Step', '智能体步骤', '智能体循环中的一次模型调用、工具调用或状态转换。', 'A single model call, tool call, or state transition within an agent loop.');
  term('agents', 'action', 'Action', '行动', '智能体依据当前状态选择并执行的操作。', 'An operation selected and executed by an agent based on its current state.');
  term('agents', 'action-space', 'Action Space', '行动空间', '智能体在特定环境中可以选择的全部行动集合。', 'The set of all actions available to an agent in a particular environment.');
  term('agents', 'environment', 'Environment', '环境', '智能体能够观察并通过行动影响的外部系统或任务世界。', 'The external system or task world an agent can observe and affect through actions.');
  term('agents', 'observation', 'Observation', '观察', '环境或工具返回给智能体、用于后续决策的信息。', 'Information returned by an environment or tool for the agent\'s subsequent decisions.');
  term('agents', 'goal', 'Goal', '目标', '智能体被要求达到的期望结果或状态。', 'A desired result or state that an agent is asked to achieve.');
  term('agents', 'objective', 'Objective', '任务目标', '用于指导并评价智能体行为的明确任务要求。', 'An explicit task requirement used to guide and assess agent behavior.');
  term('agents', 'planning', 'Planning', '规划', '在执行前或执行中形成行动步骤与依赖关系的过程。', 'The process of forming action steps and dependencies before or during execution.');
  term('agents', 'plan', 'Plan', '计划', '为达到目标而组织的一组有序或有依赖关系的行动。', 'An ordered or dependency-aware set of actions organized to reach a goal.');
  term('agents', 'reasoning', 'Reasoning', '推理', '根据输入、上下文和规则形成判断或中间结论的过程。', 'The process of forming judgments or intermediate conclusions from input, context, and rules.');
  term('agents', 'decision-making', 'Decision Making', '决策', '在多个候选行动或答案之间进行选择的过程。', 'The process of selecting among candidate actions or answers.');
  term('agents', 'autonomy', 'Autonomy', '自主性', '系统在较少逐步人工指令下选择和执行行动的能力。', 'The ability of a system to select and execute actions with limited step-by-step human instruction.');
  term('agents', 'agency', 'Agency', '能动性', '系统以目标为依据影响环境或自身状态的能力。', 'The capacity of a system to affect an environment or its own state in pursuit of goals.');
  term('agents', 'trajectory', 'Trajectory', '执行轨迹', '一次运行中按时间排列的状态、消息、行动和结果序列。', 'The time-ordered sequence of states, messages, actions, and results in a run.');
  term('agents', 'termination-condition', 'Termination Condition', '终止条件', '决定智能体运行何时应当结束的规则。', 'A rule that determines when an agent run should end.');
  term('agents', 'stopping-criterion', 'Stopping Criterion', '停止准则', '用于停止生成、搜索或迭代过程的可判定条件。', 'A testable condition used to stop generation, search, or iteration.');
  term('agents', 'max-iterations', 'Maximum Iterations', '最大迭代次数', '允许智能体循环执行的步骤数上限。', 'The upper limit on the number of steps allowed in an agent loop.');
  term('graphRecursion', 'recursion-limit', 'Recursion Limit', '递归限制', '单次图调用允许执行的 superstep 数量上限；达到上限时执行失败，而不是表示函数调用栈深度。', 'The maximum number of supersteps allowed in one graph invocation; reaching it fails the run rather than describing call-stack depth.', ['recursion_limit']);
  term('agents', 'task', 'Task', '任务', '具有输入、预期结果和完成条件的工作单元。', 'A unit of work with input, an expected result, and completion conditions.');
  term('agents', 'subtask', 'Subtask', '子任务', '由较大任务分解出的较小工作单元。', 'A smaller unit of work decomposed from a larger task.');
  term('agents', 'task-decomposition', 'Task Decomposition', '任务分解', '将复杂任务拆成更小且可管理子任务的过程。', 'The process of dividing a complex task into smaller manageable subtasks.');
  term('agents', 'delegation', 'Delegation', '委派', '把任务或决策责任交给另一个智能体或执行单元。', 'The transfer of a task or decision responsibility to another agent or execution unit.');
  term('multiAgent', 'main-agent', 'Main Agent', '主要智能体', '在多智能体结构中承担主要任务流程并可委派子任务的智能体。', 'The agent that carries the main task flow and may delegate subtasks in a multi-agent architecture.');
  term('deepSubagents', 'subagent', 'Subagent', '子智能体', '受另一个智能体委派、负责处理子任务的智能体。', 'An agent delegated by another agent to handle a subtask.', ['sub-agent']);
  term('subagentExecution', 'synchronous-subagent', 'Synchronous Subagent', '同步子智能体', '主智能体等待其执行完成并取得结果后再继续的子智能体。', 'A subagent whose main agent waits for completion and receives the result before continuing.');
  term('subagentExecution', 'asynchronous-subagent', 'Asynchronous Subagent', '异步子智能体', '主智能体把工作作为后台任务启动后可继续执行、无需等待结果的子智能体；这里的异步不等同于编程语言的 async/await。', 'A subagent started as a background task so the main agent can continue without waiting for its result; asynchronous here is distinct from language-level async/await.');
  term('subagentExecution', 'subagent-result', 'Subagent Result', '子智能体结果', '子智能体完成委派工作后返回给主智能体的结果。', 'The result returned to a main agent after a subagent completes delegated work.');
  term('deepSubagents', 'isolated-subagent-context', 'Isolated Subagent Context', '隔离的子智能体上下文', '为一次子智能体执行单独建立、不把全部中间过程写入主智能体上下文的上下文。', 'A context created separately for one subagent execution without placing its full intermediate process in the main agent context.');
  term('deepSubagents', 'stateless-subagent-messaging', 'Stateless Subagent Messaging', '无状态子智能体消息传递', '每次子智能体调用独立处理输入并以单个最终结果返回、不维持跨调用消息会话的交互方式。', 'An interaction style in which each subagent call independently handles input and returns one final result without maintaining a cross-call message session.');
  term('multiAgent', 'supervisor-agent', 'Supervisor Agent', '监督智能体', '负责选择、协调或监督其他智能体工作的智能体。', 'An agent responsible for selecting, coordinating, or supervising the work of other agents.');
  term('multiAgent', 'worker-agent', 'Worker Agent', '工作智能体', '在多智能体系统中执行被分配具体任务的智能体。', 'An agent that performs an assigned concrete task within a multi-agent system.');
  term('agents', 'react-agent', 'ReAct Agent', 'ReAct 智能体', '交替生成推理痕迹与行动，并根据观察继续推进的智能体模式。', 'An agent pattern that alternates reasoning traces and actions, then continues from observations.');
  term('agents', 'reason-and-act', 'Reason and Act', '推理与行动', '在智能体执行中交替进行推理、行动和观察的工作方式。', 'A way of working in which an agent alternates reasoning, action, and observation.');
  term('agents', 'tool-calling-agent', 'Tool Calling Agent', '工具调用智能体', '通过模型原生工具调用接口选择和执行工具的智能体。', 'An agent that selects and executes tools through a model\'s native tool-calling interface.');
  term('agents', 'conversational-agent', 'Conversational Agent', '对话智能体', '主要通过自然语言对话与用户或其他系统交互的智能体。', 'An agent that interacts primarily through natural-language conversation.');
  term('agents', 'coding-agent', 'Coding Agent', '编程智能体', '面向代码理解、生成、修改和验证任务的智能体。', 'An agent designed for code understanding, generation, modification, and verification tasks.');
  term('agents', 'research-agent', 'Research Agent', '研究智能体', '面向信息搜集、分析、综合和引用任务的智能体。', 'An agent designed for information gathering, analysis, synthesis, and citation tasks.');
  term('agents', 'agent-harness', 'Agent Harness', '智能体框架层', '为模型、工具、循环、状态和控制机制提供组合边界的软件层。', 'A software layer that composes models, tools, loops, state, and control mechanisms.');
  term('agents', 'agent-runtime', 'Agent Runtime', '智能体运行时', '负责执行智能体循环、工具调用和状态转换的运行环境。', 'The runtime environment that executes agent loops, tool calls, and state transitions.');
  term('agents', 'agent-architecture', 'Agent Architecture', '智能体架构', '定义模型、工具、记忆、控制流和外部系统如何协作的结构。', 'The structure defining how models, tools, memory, control flow, and external systems work together.');
  term('agents', 'agentic-ai', 'Agentic AI', '智能体式人工智能', '强调目标驱动、规划、工具使用和多步行动的人工智能系统范式。', 'An AI system paradigm emphasizing goal-directed planning, tool use, and multi-step action.');
  term('agents', 'agentic-workflow', 'Agentic Workflow', '智能体式工作流', '包含模型自主选择步骤或工具的工作流程。', 'A workflow in which a model autonomously selects steps or tools.');

  term('models', 'model', 'Model', '模型', '根据输入计算预测、表示或生成结果的人工智能系统。', 'An artificial-intelligence system that computes predictions, representations, or generated results from input.');
  term('llm', 'large-language-model', 'Large Language Model', '大语言模型', '在大规模文本等数据上训练、用于理解和生成语言的模型。', 'A model trained on large-scale text and related data to understand and generate language.', ['LLM']);
  term('generative', 'generative-ai', 'Generative Artificial Intelligence', '生成式人工智能', '能够根据输入生成文本、图像、音频或其他内容的人工智能。', 'Artificial intelligence capable of generating text, images, audio, or other content from input.', ['generative AI']);
  term('models', 'chat-model', 'Chat Model', '聊天模型', '以结构化消息序列为输入并生成消息响应的模型接口。', 'A model interface that accepts structured message sequences and produces message responses.');
  term('models', 'base-chat-model', 'Base Chat Model', '基础聊天模型', '对不同聊天模型提供统一调用约定的抽象接口。', 'An abstract interface providing a common invocation contract for different chat models.', ['BaseChatModel']);
  term('models', 'model-provider', 'Model Provider', '模型提供方', '托管、发布或提供模型访问接口的组织或服务。', 'An organization or service that hosts, publishes, or provides access to models.');
  term('models', 'model-endpoint', 'Model Endpoint', '模型端点', '通过网络请求接收模型输入并返回结果的服务地址。', 'A service address that receives model input and returns results over network requests.');
  term('models', 'model-adapter', 'Model Adapter', '模型适配器', '把特定模型提供方接口转换为统一模型接口的组件。', 'A component that converts a provider-specific model interface into a common model interface.');
  term('models', 'model-invocation', 'Model Invocation', '模型调用行为', '通过模型接口提交输入并取得模型输出的调用行为。', 'The act of submitting input through a model interface and receiving model output.');
  term('middlewareWrapHooks', 'model-call', 'Model Call', '模型调用', '由一次模型请求和相应模型响应构成、可被模型调用中间件包裹的执行单元。', 'An execution unit consisting of one model request and its corresponding model response that model-call middleware can wrap.');
  term('modelRequestApi', 'model-request', 'Model Request', '模型请求', '为一次模型调用准备的完整输入，通常包含消息以及工具、响应格式或模型设置等调用信息。', 'The complete input prepared for one model call, typically including messages and call information such as tools, response format, or model settings.');
  term('modelResponseApi', 'model-response', 'Model Response', '模型响应', '一次模型调用返回的消息以及可选结构化结果。', 'The messages and optional structured result returned by one model call.');
  term('models', 'model-profile', 'Model Profile', '模型能力描述', '描述模型支持的输入、输出、工具调用和限制等能力的元数据。', 'Metadata describing a model\'s supported inputs, outputs, tool calling, and limitations.');
  term('models', 'model-configuration', 'Model Configuration', '模型配置', '控制模型选择、连接和生成行为的一组参数。', 'A set of parameters controlling model selection, connectivity, and generation behavior.');
  term('models', 'model-identifier', 'Model Identifier', '模型标识符', '在提供方或系统中唯一指代某个模型或版本的名称。', 'A name that uniquely refers to a model or version within a provider or system.');
  term('models', 'foundation-model', 'Foundation Model', '基础模型', '在广泛数据上预训练并可适配多种下游任务的模型。', 'A model pretrained on broad data and adaptable to many downstream tasks.');
  term('models', 'instruction-tuned-model', 'Instruction Tuned Model', '指令微调模型', '通过指令与响应样本训练以更好遵循自然语言要求的模型。', 'A model trained on instruction-response examples to better follow natural-language requests.');
  term('models', 'reasoning-model', 'Reasoning Model', '推理模型', '针对多步骤推理和复杂问题求解进行优化的模型。', 'A model optimized for multi-step reasoning and complex problem solving.');
  term('models', 'multimodal-model', 'Multimodal Model', '多模态模型', '能够处理或生成文本、图像、音频等多种数据模态的模型。', 'A model capable of processing or generating multiple data modalities such as text, images, and audio.');
  term('models', 'context-window', 'Context Window', '上下文窗口', '模型在一次请求中能够处理的输入与输出 token 总范围。', 'The total range of input and output tokens a model can process in one request.');
  term('llm', 'token', 'Token', '词元', '模型处理文本时使用的离散符号单位。', 'A discrete symbol unit used by a model to process text.');
  term('llm', 'tokenization', 'Tokenization', '词元化', '把文本转换为模型可处理词元序列的过程。', 'The process of converting text into a sequence of tokens a model can process.');
  term('llm', 'tokenizer', 'Tokenizer', '词元器', '执行文本与词元 ID 之间编码和解码的组件。', 'A component that encodes text into token identifiers and decodes them back.');
  term('models', 'input-token', 'Input Token', '输入词元', '作为模型请求上下文提交的词元。', 'A token submitted as part of a model request context.');
  term('models', 'output-token', 'Output Token', '输出词元', '模型在生成响应时产生的词元。', 'A token produced by a model while generating a response.');
  term('models', 'token-budget', 'Token Budget', '词元预算', '为输入、输出或整个运行分配的词元数量限制。', 'A token quantity limit allocated to input, output, or an entire run.');
  term('models', 'maximum-output-tokens', 'Maximum Output Tokens', '最大输出词元数', '一次生成允许产生的输出词元上限。', 'The upper limit on output tokens allowed in one generation.');
  term('models', 'temperature', 'Temperature', '温度', '调节采样分布随机程度的生成参数。', 'A generation parameter that adjusts randomness in the sampling distribution.');
  term('models', 'top-p', 'Top P', '核采样概率阈值', '仅从累计概率达到阈值的候选词元集合中采样的参数。', 'A parameter that samples only from the smallest token set reaching a cumulative probability threshold.');
  term('models', 'nucleus-sampling', 'Nucleus Sampling', '核采样', '从累计概率达到指定阈值的最小候选词元集合中进行采样的方法。', 'A sampling method that selects from the smallest token set reaching a specified cumulative probability.');
  term('models', 'presence-penalty', 'Presence Penalty', '存在惩罚', '根据词元是否已经出现来调整其后续生成倾向的参数。', 'A parameter that adjusts future token likelihood according to whether a token has already appeared.', ['presence_penalty']);
  term('models', 'frequency-penalty', 'Frequency Penalty', '频率惩罚', '根据词元已出现次数来调整其后续生成倾向的参数。', 'A parameter that adjusts future token likelihood according to how often a token has already appeared.', ['frequency_penalty']);
  term('models', 'random-seed', 'Random Seed', '随机种子', '用于初始化随机过程、帮助重复生成行为的数值。', 'A value used to initialize randomized processing and help repeat generation behavior.');
  term('models', 'request-timeout', 'Request Timeout', '请求超时', '一次模型请求允许等待的最长时间。', 'The maximum time allowed for waiting on one model request.');
  term('models', 'maximum-retries', 'Maximum Retries', '最大重试次数', '模型请求失败后允许再尝试的最大次数。', 'The maximum number of additional attempts allowed after a model request fails.');
  term('models', 'streaming-usage-statistics', 'Streaming Usage Statistics', '流式用量统计', '控制流式响应是否包含词元用量统计的设置。', 'A setting controlling whether token usage statistics are included with streaming responses.');
  term('models', 'service-tier', 'Service Tier', '服务等级', '选择上游模型请求所使用服务等级的参数。', 'A parameter selecting the service tier used for an upstream model request.', ['service_tier']);
  term('models', 'top-k', 'Top K', '候选词元上限', '将每步采样限制在概率最高的 K 个候选词元内的参数。', 'A parameter limiting each sampling step to the K highest-probability token candidates.');
  term('models', 'sampling', 'Sampling', '采样', '根据预测概率分布选择下一词元的生成方法。', 'A generation method that selects the next token from a predicted probability distribution.');
  term('models', 'greedy-decoding', 'Greedy Decoding', '贪心解码', '每一步都选择概率最高候选词元的解码方法。', 'A decoding method that selects the highest-probability token at every step.');
  term('models', 'beam-search', 'Beam Search', '束搜索', '在生成过程中同时保留若干高分候选序列的搜索方法。', 'A search method that retains several high-scoring candidate sequences during generation.');
  term('models', 'stop-sequence', 'Stop Sequence', '停止序列', '一旦生成便触发输出终止的字符或词元序列。', 'A character or token sequence that terminates output when generated.');
  term('models', 'logit', 'Logit', '逻辑值', '模型在归一化为概率前对候选词元给出的原始分数。', 'A raw score assigned by a model to a candidate token before probability normalization.');
  term('models', 'log-probability', 'Log Probability', '对数概率', '概率取对数后的表示，常用于评估候选词元或序列。', 'The logarithmic representation of probability, often used to evaluate candidate tokens or sequences.');
  term('models', 'top-log-probabilities', 'Top Log Probabilities', '最高对数概率数量', '每个输出位置返回的最高候选词元对数概率数量。', 'The number of highest-probability token log probabilities returned at each output position.');
  term('models', 'completion', 'Completion', '续写结果', '模型依据输入前缀生成的后续内容。', 'Content generated by a model as a continuation of an input prefix.');
  term('models', 'chat-completion', 'Chat Completion', '聊天补全', '根据一组对话消息生成下一条助手消息的模型操作。', 'A model operation that generates the next assistant message from a conversation message sequence.');
  term('messages', 'message', 'Message', '消息', '带有角色、内容及可选元数据的对话数据单元。', 'A conversational data unit with a role, content, and optional metadata.');
  term('messages', 'system-message', 'System Message', '系统消息', '用于设定模型行为、角色和响应规则的指令消息。', 'An instruction message used to establish model behavior, role, and response guidelines.', ['SystemMessage']);
  term('messages', 'human-message', 'Human Message', '人类消息', '表示人类输入和交互、并可承载文本或多模态内容的消息。', 'A message representing human input and interactions that can carry text or multimodal content.', ['HumanMessage']);
  term('messages', 'user-message', 'User Message', '用户消息', '表示用户在对话中提交内容的消息。', 'A message representing content submitted by a user in a conversation.');
  term('messages', 'ai-message', 'AI Message', '人工智能消息', '表示一次模型调用输出的消息，可包含内容、工具调用和响应元数据。', 'A message representing the output of a model invocation, which can include content, tool calls, and response metadata.', ['AIMessage']);
  term('messages', 'assistant-message', 'Assistant Message', '助手消息', '在聊天协议中由助手角色生成的消息。', 'A message generated under the assistant role in a chat protocol.');
  term('messages', 'assistant-role', 'Assistant Role', '助手角色', '在聊天协议中标识模型或助手所生成消息的角色。', 'The role identifying a message generated by a model or assistant in a chat protocol.');
  term('messages', 'tool-message', 'Tool Message', '工具消息', '把一次工具执行结果传回模型、并通过调用标识关联原工具调用的消息。', 'A message that passes one tool execution result back to a model and links it to the originating tool call by its call identifier.', ['ToolMessage']);
  term('messages', 'message-role', 'Message Role', '消息角色', '标识消息在对话中来源或功能的类别。', 'A category identifying the source or function of a message in a conversation.');
  term('messages', 'message-content', 'Message Content', '消息内容', '消息承载的文本、数据块或多模态内容。', 'The text, data blocks, or multimodal content carried by a message.');
  term('messages', 'content-block', 'Content Block', '内容块', '消息中具有明确类型的结构化内容单元。', 'A typed structured unit of content within a message.');
  term('messages', 'message-sequence', 'Message Sequence', '消息序列', '按确定顺序组织并作为一组交给模型或智能体的消息集合。', 'An ordered collection of messages supplied as a group to a model or agent.');
  term('messages', 'message-history', 'Message History', '消息历史', '按时间排序并用于维持对话上下文的消息序列。', 'A time-ordered sequence of messages used to maintain conversational context.');
  term('messages', 'message-metadata', 'Message Metadata', '消息元数据', '随消息携带、用于标识、追踪或解释消息但不等同于正文的数据。', 'Data carried with a message for identification, tracing, or interpretation that is distinct from its body content.');
  term('messages', 'response-metadata', 'Response Metadata', '响应元数据', '模型提供方随人工智能消息返回的模型名称、结束原因或请求标识等响应信息。', 'Response information returned with an AI message by a model provider, such as model name, finish reason, or request identifier.');
  term('messages', 'usage-metadata', 'Usage Metadata', '用量元数据', '记录模型调用输入、输出和总词元数量等资源用量的数据。', 'Data recording resource usage for a model call, such as input, output, and total token counts.');
  term('messages', 'raw-message-content', 'Raw Message Content', '原始消息内容', '消息 content 属性中未经标准化的字符串或对象列表，可保留模型提供方原生结构。', 'The unnormalized string or object list in a message content attribute, which may preserve provider-native structures.');
  term('messages', 'provider-native-content', 'Provider-Native Content', '提供方原生内容', '按照特定模型提供方自有模式表达的消息内容结构。', 'A message-content structure expressed in a specific model provider\'s own schema.');
  term('messages', 'standard-content-block', 'Standard Content Block', '标准内容块', 'LangChain 用于跨模型提供方统一表示消息内容的带类型结构。', 'A typed structure LangChain uses to represent message content consistently across model providers.');
  term('messages', 'content-block-normalization', 'Content Block Normalization', '内容块标准化', '把提供方原生消息内容解析为统一标准内容块表示的过程。', 'The process of parsing provider-native message content into a common standard-content-block representation.');
  term('messages', 'text-content-block', 'Text Content Block', '文本内容块', '以 text 类型和文本字段表示普通文本的标准内容块。', 'A standard content block representing ordinary text with a text type and text field.', ['TextContentBlock']);
  term('messages', 'reasoning-content-block', 'Reasoning Content Block', '推理内容块', '以 reasoning 类型表示模型推理内容及可选提供方附加数据的标准内容块。', 'A standard content block representing model reasoning and optional provider-specific extras with a reasoning type.', ['ReasoningContentBlock']);
  term('messages', 'tool-call-content-block', 'Tool Call Content Block', '工具调用内容块', '以 tool_call 类型携带工具名称、参数和调用标识的标准内容块。', 'A standard content block carrying a tool name, arguments, and call identifier with a tool_call type.', ['ToolCall']);
  term('messages', 'conversation-turn', 'Conversation Turn', '对话轮次', '对话中一个参与者发言及相关响应构成的交互单位。', 'An interaction unit consisting of one participant\'s utterance and related response.');
  term('streaming', 'message-chunk', 'Message Chunk', '消息分块', '流式生成期间返回的部分消息数据。', 'Partial message data returned during streaming generation.');
  term('streaming', 'streaming', 'Streaming', '流式传输', '在完整结果产生前持续发送增量输出的方式。', 'A method of sending incremental output before the complete result is available.');
  term('streaming', 'stream-event', 'Stream Event', '流事件', '流式执行中表示特定运行阶段或数据更新的事件。', 'An event representing a specific execution stage or data update during streaming.');
  term('streamModes', 'stream-mode', 'Stream Mode', '流模式', '选择流式接口交付哪一类运行数据的模式。', 'A mode selecting which category of runtime data a streaming interface delivers.', ['stream_mode']);
  term('streamModes', 'agent-progress-stream', 'Agent Progress Stream', '智能体进度流', '在智能体步骤完成时持续交付状态更新的流。', 'A stream that delivers state updates as agent steps complete.');
  term('streamModes', 'updates-stream-mode', 'Updates Stream Mode', '状态更新流模式', '在每个智能体步骤后交付状态更新、同一步的多个更新分别发送的流模式。', 'The stream mode that emits state updates after each agent step and sends multiple updates from one step separately.', ['stream_mode=updates']);
  term('streamModes', 'messages-stream-mode', 'Messages Stream Mode', '消息流模式', '从调用模型的图节点交付词元消息分块及其元数据的流模式。', 'The stream mode that emits token message chunks and metadata from graph nodes that invoke a model.', ['stream_mode=messages']);
  term('streamModes', 'custom-stream-mode', 'Custom Stream Mode', '自定义流模式', '交付图节点或工具在执行期间主动写入的任意应用数据的流模式。', 'The stream mode that emits arbitrary application data explicitly written by graph nodes or tools during execution.', ['stream_mode=custom']);
  term('streamModes', 'custom-stream-update', 'Custom Stream Update', '自定义流更新', '图节点或工具在执行期间通过流写入器发出的应用自定义数据。', 'Application-defined data emitted by a graph node or tool through a stream writer during execution.');
  term('streaming', 'multi-mode-streaming', 'Multi-Mode Streaming', '多模式流式传输', '在同一次流式调用中同时选择并区分多种流模式的方式。', 'A way to select and distinguish multiple stream modes in one streaming invocation.');
  term('streaming', 'token-streaming', 'Token Streaming', '词元流式输出', '在生成过程中逐步交付词元或文本片段。', 'The progressive delivery of tokens or text fragments during generation.');
  term('streaming', 'backpressure', 'Backpressure', '背压', '下游处理速度不足时限制上游数据产生速率的机制。', 'A mechanism that limits upstream data production when downstream processing is slower.');

  term('prompt', 'prompt', 'Prompt', '提示', '提供给生成模型、用于引导其输出的输入内容。', 'Input provided to a generative model to guide its output.');
  term('prompt', 'prompt-engineering', 'Prompt Engineering', '提示工程', '设计、测试和改进模型输入以获得期望行为的实践。', 'The practice of designing, testing, and improving model inputs to obtain desired behavior.');
  term('agents', 'system-prompt', 'System Prompt', '系统提示', '用于设定模型整体行为、角色和约束的高优先级提示。', 'A high-priority prompt that establishes a model\'s overall behavior, role, and constraints.', ['system_prompt']);
  term('prompt', 'user-prompt', 'User Prompt', '用户提示', '由用户提供、表达问题、任务或要求的提示内容。', 'Prompt content supplied by a user to express a question, task, or request.');
  term('prompt', 'instruction', 'Instruction', '指令', '描述模型应执行何种任务或遵循何种行为的文本。', 'Text describing a task the model should perform or behavior it should follow.');
  term('prompt', 'instruction-hierarchy', 'Instruction Hierarchy', '指令层级', '用于规定不同来源指令优先顺序的规则体系。', 'A rule system defining precedence among instructions from different sources.');
  term('prompt', 'prompt-template', 'Prompt Template', '提示模板', '包含固定文本和待填变量、可重复实例化的提示结构。', 'A reusable prompt structure containing fixed text and variables to be filled.');
  term('prompt', 'prompt-variable', 'Prompt Variable', '提示变量', '在提示模板实例化时被具体值替换的占位字段。', 'A placeholder field replaced with a concrete value when a prompt template is instantiated.');
  term('prompt', 'prompt-prefix', 'Prompt Prefix', '提示前缀', '置于主要输入之前、用于建立任务背景或行为的提示部分。', 'The part of a prompt placed before the main input to establish task context or behavior.');
  term('prompt', 'prompt-suffix', 'Prompt Suffix', '提示后缀', '置于主要输入之后、用于约束格式或触发回答的提示部分。', 'The part of a prompt placed after the main input to constrain format or trigger a response.');
  term('prompt', 'zero-shot-prompting', 'Zero Shot Prompting', '零样本提示', '不给出示例，仅通过任务说明要求模型完成任务的方法。', 'A method that asks a model to perform a task using instructions without examples.');
  term('prompt', 'one-shot-prompting', 'One Shot Prompting', '单样本提示', '在提示中提供一个示例来说明任务的方法。', 'A method that provides one example in the prompt to illustrate a task.');
  term('prompt', 'few-shot-prompting', 'Few Shot Prompting', '少样本提示', '在提示中提供少量输入输出示例来引导模型的方法。', 'A method that provides a small number of input-output examples to guide a model.');
  term('prompt', 'in-context-learning', 'In Context Learning', '上下文学习', '模型根据当前上下文中的指令或示例调整输出而不更新参数的现象。', 'The ability of a model to adapt output from instructions or examples in the current context without parameter updates.');
  term('prompt', 'demonstration', 'Demonstration', '示范样本', '提示中用于展示期望任务行为的输入输出示例。', 'An input-output example in a prompt that demonstrates desired task behavior.');
  term('prompt', 'chain-of-thought', 'Chain of Thought', '思维链', '把复杂问题表示为一系列中间推理步骤的方法或输出形式。', 'A method or output form representing a complex problem as a series of intermediate reasoning steps.', ['CoT']);
  term('prompt', 'zero-shot-chain-of-thought', 'Zero Shot Chain of Thought', '零样本思维链', '不提供推理示例而通过指令诱导分步推理的方法。', 'A method that elicits stepwise reasoning through an instruction without reasoning examples.');
  term('prompt', 'self-consistency', 'Self Consistency', '自洽采样', '生成多条推理路径并聚合其答案以提高稳定性的方法。', 'A method that samples multiple reasoning paths and aggregates their answers for greater robustness.');
  term('prompt', 'tree-of-thoughts', 'Tree of Thoughts', '思维树', '以分支结构探索、评估和选择多条中间推理路径的方法。', 'A method that explores, evaluates, and selects intermediate reasoning paths in a branching structure.');
  term('prompt', 'scratchpad', 'Scratchpad', '推理草稿区', '用于保存中间计算、计划或推理内容的临时上下文区域。', 'A temporary context area used to hold intermediate calculations, plans, or reasoning.');
  term('prompt', 'reasoning-trace', 'Reasoning Trace', '推理轨迹', '记录模型或智能体中间推理步骤的序列。', 'A sequence recording intermediate reasoning steps of a model or agent.');
  term('prompt', 'rationale', 'Rationale', '理由说明', '用于解释答案或决策依据的文本。', 'Text explaining the basis for an answer or decision.');
  term('prompt', 'role-prompting', 'Role Prompting', '角色提示', '通过指定身份、专业角色或视角来引导模型响应的方法。', 'A method that guides model responses by specifying an identity, professional role, or perspective.');
  term('prompt', 'persona', 'Persona', '角色设定', '为模型交互规定的身份、语气和行为特征集合。', 'A set of identity, tone, and behavioral characteristics specified for model interaction.');
  term('prompt', 'prompt-chaining', 'Prompt Chaining', '提示链', '把一个任务拆为多个提示，并将前一步输出传给后一步的方法。', 'A method that splits a task into multiple prompts and passes outputs between successive steps.');
  term('prompt', 'meta-prompt', 'Meta Prompt', '元提示', '用于生成、评估或改写其他提示的提示。', 'A prompt used to generate, evaluate, or revise other prompts.');
  term('prompt', 'prompt-optimization', 'Prompt Optimization', '提示优化', '通过人工或自动搜索改进提示表现的过程。', 'The process of improving prompt performance through manual or automated search.');
  term('prompt', 'prompt-compression', 'Prompt Compression', '提示压缩', '在尽量保留有效信息的同时减少提示长度的过程。', 'The process of reducing prompt length while preserving useful information as much as possible.');
  term('context', 'context', 'Context', '上下文', '模型在生成当前输出时可访问的输入信息集合。', 'The set of input information available to a model when generating the current output.');
  term('context', 'context-engineering', 'Context Engineering', '上下文工程', '选择、组织和动态提供模型所需上下文的实践。', 'The practice of selecting, organizing, and dynamically providing the context a model needs.');
  term('context', 'context-management', 'Context Management', '上下文管理', '在有限上下文窗口内添加、保留、压缩或移除信息的过程。', 'The process of adding, retaining, compressing, or removing information within a finite context window.');
  term('context', 'context-injection', 'Context Injection', '上下文注入', '在模型调用前把外部或运行时信息加入输入上下文的过程。', 'The process of adding external or runtime information to input context before a model call.');
  term('context', 'context-selection', 'Context Selection', '上下文选择', '从候选信息中挑选与当前任务最相关内容的过程。', 'The process of choosing information most relevant to the current task from candidates.');
  term('context', 'context-pruning', 'Context Pruning', '上下文裁剪', '移除低相关、重复或过时上下文以控制长度的过程。', 'The process of removing low-relevance, duplicate, or stale context to control length.');
  term('context', 'context-summarization', 'Context Summarization', '上下文摘要', '用更短表示概括较长上下文主要信息的过程。', 'The process of condensing the main information of a longer context into a shorter representation.');
  term('context', 'context-overflow', 'Context Overflow', '上下文溢出', '输入和预期输出超过模型上下文窗口容量的情况。', 'A condition where input and expected output exceed a model\'s context-window capacity.');
  term('context', 'lost-in-the-middle', 'Lost in the Middle', '中部信息遗失', '模型对长上下文中间位置的信息利用率较低的现象。', 'The tendency of models to use information in the middle of long contexts less effectively.');
  term('context', 'progressive-disclosure', 'Progressive Disclosure', '渐进披露', '仅在需要时逐步提供更详细信息的上下文组织原则。', 'A context-organization principle that reveals more detailed information only when needed.');
  term('context', 'dynamic-prompt', 'Dynamic Prompt', '动态提示', '在运行时依据状态、用户或外部数据构造的提示。', 'A prompt constructed at runtime from state, user information, or external data.');
  term('context', 'static-prompt', 'Static Prompt', '静态提示', '在运行期间内容保持固定的提示。', 'A prompt whose content remains fixed during execution.');
  term('context', 'runtime-context', 'Runtime Context', '运行时上下文', '执行时可供模型、工具或中间件读取的环境与调用信息。', 'Environment and invocation information available to models, tools, or middleware during execution.');

  term('tools', 'tool', 'Tool', '工具', '具有明确输入约定、可由模型请求调用以执行操作的能力。', 'A capability with a defined input contract that a model can request to execute an operation.');
  term('tools', 'custom-tool', 'Custom Tool', '自定义工具', '由应用开发者定义并暴露给模型使用的工具。', 'A tool defined by an application developer and exposed for model use.');
  term('tools', 'built-in-tool', 'Built In Tool', '内置工具', '由模型平台或智能体框架直接提供的工具能力。', 'A tool capability provided directly by a model platform or agent framework.');
  term('tools', 'tool-calling', 'Tool Calling', '工具调用', '模型生成结构化请求以选择工具并提供参数的能力。', 'The ability of a model to produce a structured request selecting a tool and supplying arguments.');
  term('tools', 'tool-call', 'Tool Call', '工具调用请求', '模型输出的、包含工具名称和参数的结构化调用请求。', 'A structured invocation request produced by a model containing a tool name and arguments.');
  term('tools', 'tool-result', 'Tool Result', '工具结果', '工具执行后返回给模型或运行时的数据。', 'Data returned to a model or runtime after tool execution.');
  term('tools', 'tool-name', 'Tool Name', '工具名称', '在可用工具集合中标识某个工具的名称。', 'A name identifying a tool within the available tool set.');
  term('tools', 'tool-description', 'Tool Description', '工具描述', '向模型说明工具用途、适用场景和行为的文本。', 'Text explaining a tool\'s purpose, appropriate use, and behavior to a model.', ['tool_description']);
  term('tools', 'tool-argument', 'Tool Argument', '工具参数', '工具调用中传给工具的命名或位置输入值。', 'A named or positional input value passed to a tool call.');
  term('tools', 'tool-schema', 'Tool Schema', '工具模式', '描述工具参数名称、类型、约束和必填关系的结构。', 'A structure describing tool argument names, types, constraints, and required fields.');
  term('tools', 'argument-schema', 'Argument Schema', '参数模式', '定义调用参数结构和验证规则的模式。', 'A schema defining the structure and validation rules of invocation arguments.');
  term('tools', 'tool-binding', 'Tool Binding', '工具绑定', '将一组工具定义关联到模型调用接口的过程。', 'The process of associating a set of tool definitions with a model invocation interface.');
  term('tools', 'tool-selection', 'Tool Selection', '工具选择', '从可用工具中决定使用哪个工具的过程。', 'The process of deciding which tool to use from those available.');
  term('tools', 'tool-routing', 'Tool Routing', '工具路由', '依据请求或状态把调用导向合适工具的机制。', 'A mechanism that directs a call to an appropriate tool based on a request or state.');
  term('tools', 'parallel-tool-calling', 'Parallel Tool Calling', '并行工具调用', '在同一模型步骤中请求并发执行多个相互独立工具的方式。', 'A mode that requests concurrent execution of multiple independent tools in one model step.');
  term('tools', 'sequential-tool-calling', 'Sequential Tool Calling', '串行工具调用', '按顺序执行工具并将前一结果用于后续调用的方式。', 'A mode that executes tools in order and uses earlier results in later calls.');
  term('tools', 'tool-choice', 'Tool Choice', '工具选择策略', '控制模型是否、何时或必须调用特定工具的设置。', 'A setting controlling whether, when, or which specific tool a model must call.');
  term('tools', 'tool-error', 'Tool Error', '工具错误', '工具执行或参数验证失败时产生的错误结果。', 'An error result produced when tool execution or argument validation fails.');
  term('tools', 'tool-retry', 'Tool Retry', '工具重试', '工具调用失败后依据策略再次执行的机制。', 'A mechanism that executes a tool again according to a policy after failure.');
  term('tools', 'tool-timeout', 'Tool Timeout', '工具超时', '工具调用超过允许时间后被终止或判定失败的情况。', 'A condition where a tool call is terminated or marked failed after exceeding its allowed time.');
  term('tools', 'tool-policy', 'Tool Policy', '工具策略', '规定工具可见性、权限、选择和执行条件的规则集合。', 'A set of rules governing tool visibility, permissions, selection, and execution conditions.');
  term('tools', 'tool-allowlist', 'Tool Allowlist', '工具允许列表', '明确列出允许被模型访问或执行的工具集合。', 'An explicit set of tools permitted for model access or execution.');
  term('tools', 'tool-denylist', 'Tool Denylist', '工具拒绝列表', '明确列出禁止被模型访问或执行的工具集合。', 'An explicit set of tools prohibited from model access or execution.');
  term('tools', 'tool-visibility', 'Tool Visibility', '工具可见性', '决定某个工具定义是否出现在模型可用工具表面的属性。', 'A property determining whether a tool definition appears in the model\'s available tool surface.');
  term('tools', 'tool-surface', 'Tool Surface', '工具表面', '在一次模型请求中实际向模型公开的工具集合及其模式。', 'The tools and schemas actually exposed to a model in a particular request.');
  term('tools', 'function-calling', 'Function Calling', '函数调用', '模型以结构化参数请求应用函数的一类工具调用机制。', 'A tool-calling mechanism in which a model requests an application function with structured arguments.');
  term('structured', 'structured-output', 'Structured Output', '结构化输出', '按照预定义数据模式生成并验证的模型输出。', 'Model output generated and validated against a predefined data schema.');
  term('structured', 'output-schema', 'Output Schema', '输出结构规范', '定义结构化响应字段、类型和约束的规范。', 'A schema defining the fields, types, and constraints of a structured response.');
  term('structured', 'response-format', 'Response Format', '响应格式', '规定模型响应应采用何种结构或表示形式的设置。', 'A setting specifying the structure or representation a model response should use.');
  term('structured', 'schema-validation', 'Schema Validation', '模式验证', '检查数据是否符合预定义模式规则的过程。', 'The process of checking whether data conforms to predefined schema rules.');
  term('structured', 'provider-strategy', 'Provider Strategy', '提供方结构化策略', '利用模型提供方原生结构化输出能力生成响应的策略。', 'A strategy that uses a model provider\'s native structured-output capability.');
  term('structured', 'tool-strategy', 'Tool Strategy', '工具结构化策略', '借助工具调用机制生成符合指定模式响应的策略。', 'A strategy that uses tool calling to produce a response conforming to a specified schema.');
  term('structured', 'constrained-decoding', 'Constrained Decoding', '约束解码', '在生成时限制可选输出以满足语法或模式要求的解码方法。', 'A decoding method that restricts possible output during generation to satisfy grammar or schema requirements.');
  term('structured', 'grammar-constrained-generation', 'Grammar Constrained Generation', '语法约束生成', '要求生成结果符合形式语法的文本生成方法。', 'A text-generation method requiring output to conform to a formal grammar.');
  term('middleware', 'middleware', 'Middleware', '中间件', '在智能体执行流程的指定阶段插入控制、修改或观测逻辑的组件概念。', 'A component concept that inserts control, modification, or observation logic at designated stages of agent execution.');
  term('middlewareHooks', 'middleware-hook', 'Middleware Hook', '中间件钩子', '在智能体执行生命周期的指定位置调用自定义逻辑的扩展点。', 'An extension point that invokes custom logic at a designated position in an agent execution lifecycle.');
  term('middlewareHooks', 'node-style-hook', 'Node-Style Hook', '节点式钩子', '在智能体或模型调用前后作为独立图节点运行、并可直接返回状态更新的中间件钩子。', 'A middleware hook that runs as a separate graph node before or after agent or model execution and can return state updates directly.');
  term('middlewareWrapHooks', 'wrap-style-hook', 'Wrap-Style Hook', '包裹式钩子', '包围模型或工具调用、并控制下游处理器调用零次、一次或多次的中间件钩子。', 'A middleware hook that surrounds a model or tool call and controls whether its downstream handler runs zero, one, or multiple times.');
  term('middlewareWrapHooks', 'model-call-handler', 'Model Call Handler', '模型调用处理器', '包裹式模型钩子用于把请求传给下一层中间件或模型并取得响应的可调用对象。', 'The callable a wrap-style model hook uses to pass a request to the next middleware layer or model and obtain a response.');
  term('middlewareWrapHooks', 'short-circuit', 'Short Circuit', '短路', '在不调用下游处理器的情况下直接返回结果、从而跳过后续执行的控制流。', 'Control flow that returns a result without calling the downstream handler, thereby skipping later execution.');
  term('middlewareOrder', 'middleware-composition', 'Middleware Composition', '中间件组合', '把多个中间件层组合成一个执行链，并按钩子类型应用嵌套或先后顺序的过程。', 'The process of combining multiple middleware layers into an execution chain with nesting or sequencing determined by hook type.');
  term('middlewareOrder', 'middleware-execution-order', 'Middleware Execution Order', '中间件执行顺序', '规定多个中间件的前置、包裹和后置钩子以何种先后关系运行的顺序规则。', 'The ordering rules that determine how pre, wrap, and post hooks from multiple middleware run relative to one another.');
  term('middleware', 'model-call-middleware', 'Model Call Middleware', '模型调用中间件', '在模型请求前后运行并可修改请求或响应的中间处理逻辑。', 'Intermediate logic that runs around model calls and may modify requests or responses.');
  term('middleware', 'tool-call-middleware', 'Tool Call Middleware', '工具调用中间件', '在工具执行前后运行并可控制参数、结果或错误的中间处理逻辑。', 'Intermediate logic that runs around tool execution and may control arguments, results, or errors.');
  term('middleware', 'dynamic-tool-selection', 'Dynamic Tool Selection', '动态工具选择', '根据当前状态在运行时改变模型可用工具集合的机制。', 'A mechanism that changes the tools available to a model at runtime based on current state.');
  term('middleware', 'dynamic-model-selection', 'Dynamic Model Selection', '动态模型选择', '根据请求、状态或策略在运行时选择模型的机制。', 'A mechanism that selects a model at runtime based on a request, state, or policy.');
  term('middleware', 'model-fallback', 'Model Fallback', '模型回退', '首选模型失败或不适用时改用备用模型的机制。', 'A mechanism that uses an alternative model when the preferred model fails or is unsuitable.');
  term('middleware', 'model-retry', 'Model Retry', '模型重试', '模型调用失败后依据策略再次请求的机制。', 'A mechanism that repeats a model request according to a policy after failure.');
  term('middleware', 'rate-limiting', 'Rate Limiting', '速率限制', '限制单位时间内模型或工具调用数量的控制机制。', 'A control mechanism limiting the number of model or tool calls per unit time.');
  term('middleware', 'request-interception', 'Request Interception', '请求拦截', '在请求到达模型或工具前捕获并处理它的机制。', 'A mechanism that captures and processes a request before it reaches a model or tool.');
  term('middleware', 'response-interception', 'Response Interception', '响应拦截', '在响应返回调用方前捕获并处理它的机制。', 'A mechanism that captures and processes a response before it returns to the caller.');

  term('retrieval', 'retrieval', 'Retrieval', '检索', '根据查询从外部信息集合中找出相关内容的过程。', 'The process of finding relevant content in an external information collection from a query.');
  term('rag', 'retrieval-augmented-generation', 'Retrieval Augmented Generation', '检索增强生成', '先检索外部信息，再将其作为上下文用于生成响应的方法。', 'A method that retrieves external information and uses it as context for response generation.', ['RAG']);
  term('rag', 'grounding', 'Grounding', '依据约束', '使模型输出以给定证据、数据或环境状态为依据的过程。', 'The process of anchoring model output in supplied evidence, data, or environment state.');
  term('rag', 'grounded-generation', 'Grounded Generation', '有依据生成', '基于可识别外部证据生成内容的方法。', 'A method of generating content based on identifiable external evidence.');
  term('rag', 'knowledge-grounding', 'Knowledge Grounding', '知识依据化', '将模型回答关联到选定知识来源的过程。', 'The process of linking model answers to selected knowledge sources.');
  term('retrieval', 'retriever', 'Retriever', '检索器', '接收查询并返回相关文档或数据项的组件概念。', 'A component concept that accepts a query and returns relevant documents or data items.');
  term('retrieval', 'document', 'Document', '文档', '可被索引、检索并作为上下文使用的信息单元。', 'An information unit that can be indexed, retrieved, and used as context.');
  term('retrieval', 'document-loader', 'Document Loader', '文档加载器', '从数据源读取内容并转换为统一文档表示的组件。', 'A component that reads content from a data source and converts it into a common document representation.');
  term('retrieval', 'document-transformation', 'Document Transformation', '文档转换', '对文档进行拆分、清理、增强或重组的过程。', 'The process of splitting, cleaning, enriching, or reorganizing documents.');
  term('retrieval', 'text-splitting', 'Text Splitting', '文本拆分', '把长文本划分为较小可检索片段的过程。', 'The process of dividing long text into smaller retrievable segments.');
  term('retrieval', 'text-splitter', 'Text Splitter', '文本拆分器', '依据长度、结构或语义边界划分文本的组件。', 'A component that divides text according to length, structure, or semantic boundaries.');
  term('retrieval', 'chunk', 'Chunk', '文本块', '为索引、检索或上下文注入而形成的较小内容片段。', 'A smaller content segment created for indexing, retrieval, or context injection.');
  term('retrieval', 'chunk-size', 'Chunk Size', '文本块大小', '单个文本块允许包含的字符、词元或其他单位数量。', 'The number of characters, tokens, or other units allowed in one chunk.');
  term('retrieval', 'chunk-overlap', 'Chunk Overlap', '文本块重叠', '相邻文本块之间重复保留的内容范围。', 'The amount of content retained in common between adjacent chunks.');
  term('retrieval', 'semantic-chunking', 'Semantic Chunking', '语义分块', '依据主题或语义变化而非固定长度划分内容的方法。', 'A method that divides content by topic or semantic shifts rather than fixed length.');
  term('retrieval', 'recursive-splitting', 'Recursive Splitting', '递归拆分', '按一组层级分隔规则反复细分文本的方法。', 'A method that repeatedly subdivides text using a hierarchy of separators.');
  term('vector', 'embedding', 'Embedding', '嵌入向量', '把文本、图像或其他对象映射为数值向量的表示。', 'A numerical vector representation of text, images, or other objects.');
  term('vector', 'embedding-model', 'Embedding Model', '嵌入模型', '将输入转换为向量表示的模型。', 'A model that converts input into vector representations.');
  term('vector', 'embedding-dimension', 'Embedding Dimension', '嵌入维度', '嵌入向量所包含数值分量的数量。', 'The number of numerical components in an embedding vector.');
  term('vector', 'vector-store', 'Vector Store', '向量存储', '保存向量及相关元数据并支持相似性查询的存储系统概念。', 'A storage-system concept that holds vectors and metadata and supports similarity queries.');
  term('vector', 'vector-database', 'Vector Database', '向量数据库', '针对高维向量存储、索引和查询优化的数据库。', 'A database optimized for storing, indexing, and querying high-dimensional vectors.');
  term('vector', 'vector-index', 'Vector Index', '向量索引', '用于加速相似向量查找的数据结构。', 'A data structure used to accelerate searches for similar vectors.');
  term('vector', 'similarity-search', 'Similarity Search', '相似性搜索', '依据表示之间的距离或相似度寻找近似项的过程。', 'The process of finding nearby items according to distance or similarity between representations.');
  term('vector', 'semantic-search', 'Semantic Search', '语义搜索', '依据查询与内容的含义相似性而非仅字面匹配进行搜索的方法。', 'A search method based on similarity of meaning rather than only literal matching.');
  term('vector', 'nearest-neighbor-search', 'Nearest Neighbor Search', '最近邻搜索', '在度量空间中寻找距离查询点最近数据项的搜索问题。', 'The search problem of finding data items closest to a query point in a metric space.');
  term('vector', 'approximate-nearest-neighbor', 'Approximate Nearest Neighbor', '近似最近邻', '用近似结果换取更高搜索效率的最近邻方法。', 'A nearest-neighbor method that trades exactness for improved search efficiency.', ['ANN']);
  term('vector', 'cosine-similarity', 'Cosine Similarity', '余弦相似度', '通过向量夹角余弦衡量方向相似性的指标。', 'A metric measuring directional similarity using the cosine of the angle between vectors.');
  term('vector', 'dot-product', 'Dot Product', '点积', '将两个向量对应分量乘积求和得到的相似性运算。', 'A similarity operation that sums products of corresponding vector components.');
  term('vector', 'euclidean-distance', 'Euclidean Distance', '欧氏距离', '度量欧氏空间中两点直线距离的指标。', 'A metric measuring straight-line distance between two points in Euclidean space.');
  term('search', 'keyword-search', 'Keyword Search', '关键词搜索', '依据查询词与内容中的字面词项匹配进行检索的方法。', 'A retrieval method based on literal term matches between a query and content.');
  term('search', 'full-text-search', 'Full Text Search', '全文搜索', '对文档完整文本建立索引并进行词项查询的方法。', 'A method that indexes complete document text and supports term queries.');
  term('search', 'sparse-retrieval', 'Sparse Retrieval', '稀疏检索', '使用大部分维度为零的词项表示进行检索的方法。', 'A retrieval method using term representations in which most dimensions are zero.');
  term('search', 'dense-retrieval', 'Dense Retrieval', '稠密检索', '使用稠密向量表示查询和文档进行相似性检索的方法。', 'A retrieval method using dense vector representations of queries and documents.');
  term('search', 'hybrid-search', 'Hybrid Search', '混合搜索', '结合关键词、向量或其他多种检索信号的方法。', 'A method combining keyword, vector, or other retrieval signals.');
  term('search', 'bm25', 'BM25', 'BM25 排序', '基于词频、逆文档频率和文档长度的概率相关性排序函数。', 'A probabilistic relevance-ranking function based on term frequency, inverse document frequency, and document length.');
  term('retrieval', 'query', 'Query', '查询', '用于表达信息需求并提交给检索系统的输入。', 'Input expressing an information need and submitted to a retrieval system.');
  term('retrieval', 'query-rewriting', 'Query Rewriting', '查询改写', '为改善检索效果而重新表达原始查询的过程。', 'The process of reformulating an original query to improve retrieval.');
  term('retrieval', 'query-expansion', 'Query Expansion', '查询扩展', '向查询加入相关词项或概念以提高召回的过程。', 'The process of adding related terms or concepts to a query to improve recall.');
  term('retrieval', 'multi-query-retrieval', 'Multi Query Retrieval', '多查询检索', '从一个信息需求生成多个查询并合并检索结果的方法。', 'A method that generates multiple queries from one information need and combines their results.');
  term('retrieval', 'self-querying', 'Self Querying', '自查询', '由模型把自然语言需求转换为结构化检索查询的方法。', 'A method in which a model converts a natural-language need into a structured retrieval query.');
  term('retrieval', 'metadata-filter', 'Metadata Filter', '元数据过滤', '依据文档元数据条件限制检索候选项的规则。', 'A rule limiting retrieval candidates according to document metadata conditions.');
  term('retrieval', 'reranking', 'Reranking', '重排序', '使用额外模型或信号重新排列初步检索结果的过程。', 'The process of reordering initial retrieval results using an additional model or signal.');
  term('retrieval', 'reranker', 'Reranker', '重排序器', '为查询与候选文档计算新相关性顺序的模型或组件。', 'A model or component that computes a new relevance ordering for a query and candidate documents.');
  term('retrieval', 'cross-encoder', 'Cross Encoder', '交叉编码器', '联合编码查询和候选文本以计算相关性分数的模型。', 'A model that jointly encodes a query and candidate text to compute a relevance score.');
  term('retrieval', 'bi-encoder', 'Bi Encoder', '双编码器', '分别编码查询和文档以便高效比较表示的模型。', 'A model that encodes queries and documents separately for efficient representation comparison.');
  term('retrieval', 'contextual-compression', 'Contextual Compression', '上下文压缩检索', '根据查询从检索内容中提取或保留最相关部分的过程。', 'The process of extracting or retaining the most query-relevant portions of retrieved content.');
  term('retrieval', 'parent-document-retrieval', 'Parent Document Retrieval', '父文档检索', '用小片段匹配查询，再返回其较大父级上下文的方法。', 'A method that matches queries with small chunks and returns their larger parent context.');
  term('retrieval', 'maximum-marginal-relevance', 'Maximum Marginal Relevance', '最大边际相关性', '在相关性与结果多样性之间进行权衡的选择方法。', 'A selection method balancing relevance against diversity among results.', ['MMR']);
  term('retrieval', 'retrieval-score', 'Retrieval Score', '检索分数', '表示查询与候选内容相关程度的数值。', 'A numerical value representing relevance between a query and candidate content.');
  term('retrieval', 'relevance', 'Relevance', '相关性', '信息项满足特定查询或信息需求的程度。', 'The degree to which an information item satisfies a particular query or information need.');
  term('retrieval', 'precision', 'Precision', '查准率', '检索结果中相关项所占的比例。', 'The proportion of retrieved items that are relevant.');
  term('retrieval', 'recall', 'Recall', '查全率', '全部相关项中被成功检索出的比例。', 'The proportion of all relevant items that are successfully retrieved.');
  term('retrieval', 'mean-reciprocal-rank', 'Mean Reciprocal Rank', '平均倒数排名', '首个相关结果排名倒数在多个查询上的平均值。', 'The average reciprocal rank of the first relevant result across queries.', ['MRR']);
  term('retrieval', 'normalized-discounted-cumulative-gain', 'Normalized Discounted Cumulative Gain', '归一化折损累计增益', '考虑相关性等级与排名位置的检索排序指标。', 'A retrieval-ranking metric accounting for graded relevance and result position.', ['NDCG']);
  term('rag', 'citation', 'Citation', '引用', '明确指出回答所依据外部来源的标记或说明。', 'A marker or statement explicitly identifying an external source supporting an answer.');
  term('rag', 'source-attribution', 'Source Attribution', '来源归属', '把生成内容中的陈述关联到其信息来源的过程。', 'The process of linking statements in generated content to their information sources.');
  term('rag', 'evidence', 'Evidence', '证据', '用于支持、反驳或检验某项陈述的信息。', 'Information used to support, refute, or test a claim.');
  term('rag', 'answer-faithfulness', 'Answer Faithfulness', '回答忠实度', '生成回答中的陈述受到所给上下文支持的程度。', 'The degree to which claims in a generated answer are supported by the provided context.');

  term('shortMemory', 'memory', 'Memory', '记忆', '使智能体能够在后续步骤或交互中利用先前信息的机制。', 'A mechanism enabling an agent to use prior information in later steps or interactions.');
  term('shortMemory', 'short-term-memory', 'Short Term Memory', '短期记忆', '在同一会话或线程范围内保留和使用信息的记忆。', 'Memory that retains and uses information within a session or thread.');
  term('longMemory', 'long-term-memory', 'Long Term Memory', '长期记忆', '跨会话或线程持久保存并可再次检索的信息。', 'Information persisted and retrievable across sessions or threads.');
  term('shortMemory', 'conversation-memory', 'Conversation Memory', '对话记忆', '保存并利用对话消息或其摘要的记忆形式。', 'A form of memory that retains and uses conversation messages or their summaries.');
  term('shortMemory', 'working-memory', 'Working Memory', '工作记忆', '智能体执行当前任务时主动维护的临时信息。', 'Temporary information actively maintained by an agent while performing the current task.');
  term('longMemory', 'semantic-memory', 'Semantic Memory', '语义记忆', '保存事实、概念及其关系的长期记忆形式。', 'A form of long-term memory storing facts, concepts, and their relationships.');
  term('longMemory', 'episodic-memory', 'Episodic Memory', '情景记忆', '保存特定经历、事件或交互轨迹的记忆形式。', 'A form of memory storing specific experiences, events, or interaction trajectories.');
  term('longMemory', 'procedural-memory', 'Procedural Memory', '程序性记忆', '保存完成任务方法、规则或技能的记忆形式。', 'A form of memory storing methods, rules, or skills for performing tasks.');
  term('longMemory', 'memory-store', 'Memory Store', '记忆存储', '保存并提供智能体记忆读写和检索能力的存储抽象。', 'A storage abstraction providing read, write, and retrieval capabilities for agent memory.');
  term('longMemory', 'memory-namespace', 'Memory Namespace', '记忆命名空间', '用于组织和隔离不同用户、智能体或类别记忆的逻辑范围。', 'A logical scope used to organize and isolate memories by user, agent, or category.');
  term('longMemory', 'memory-key', 'Memory Key', '记忆键', '在记忆存储中标识特定记录的键。', 'A key identifying a particular record in a memory store.');
  term('longMemory', 'memory-retrieval', 'Memory Retrieval', '记忆检索', '根据当前任务从已保存记忆中找出相关信息的过程。', 'The process of finding relevant information in stored memory for the current task.');
  term('longMemory', 'memory-consolidation', 'Memory Consolidation', '记忆巩固', '将临时经历整理、压缩或转化为较稳定长期记忆的过程。', 'The process of organizing, compressing, or converting temporary experiences into more stable long-term memory.');
  term('longMemory', 'memory-decay', 'Memory Decay', '记忆衰减', '记忆随时间或使用策略降低权重、精度或可访问性的现象。', 'The reduction of memory weight, fidelity, or accessibility over time or by policy.');
  term('longMemory', 'memory-reflection', 'Memory Reflection', '记忆反思', '从多条经历中归纳更高层结论或经验的过程。', 'The process of deriving higher-level conclusions or lessons from multiple experiences.');
  term('shortMemory', 'state', 'State', '状态', '在执行过程中描述系统当前信息并可随步骤更新的数据。', 'Data describing current system information that can be updated during execution.');
  term('shortMemory', 'state-schema', 'State Schema', '状态模式', '定义状态字段、类型和更新约定的模式。', 'A schema defining state fields, types, and update conventions.');
  term('shortMemory', 'state-update', 'State Update', '状态更新', '执行步骤对共享状态产生的增量或替换变化。', 'An incremental or replacement change made to shared state by an execution step.');
  term('shortMemory', 'thread', 'Thread', '线程会话', '用于归组同一连续交互及其状态的逻辑会话标识。', 'A logical session identity grouping a continuous interaction and its state.');
  term('shortMemory', 'thread-identifier', 'Thread Identifier', '线程标识符', '用于区分和恢复不同有状态会话的唯一标识。', 'A unique identifier used to distinguish and resume stateful sessions.');
  term('persistence', 'persistence', 'Persistence', '持久化', '使状态或记忆在进程、步骤或会话之后仍可保存的能力。', 'The ability to preserve state or memory beyond a process, step, or session.');
  term('persistence', 'checkpoint', 'Checkpoint', '检查点', '在特定执行时刻保存的状态快照。', 'A snapshot of state saved at a particular point in execution.');
  term('persistence', 'checkpointer', 'Checkpointer', '检查点保存器', '负责保存和读取执行状态检查点的组件。', 'A component responsible for saving and reading execution-state checkpoints.');
  term('persistence', 'checkpoint-identifier', 'Checkpoint Identifier', '检查点标识符', '唯一指代某个已保存状态快照的标识。', 'An identifier uniquely referring to a saved state snapshot.');
  term('persistence', 'durable-execution', 'Durable Execution', '持久执行', '在中断或故障后能够从已保存状态继续的执行方式。', 'An execution mode that can continue from saved state after interruption or failure.');
  term('persistence', 'fault-tolerance', 'Fault Tolerance', '容错性', '系统在部分故障发生时继续运行或恢复的能力。', 'The ability of a system to continue operating or recover when partial failures occur.');
  term('persistence', 'replay', 'Replay', '重放', '依据已记录输入、事件或状态重新执行过程的机制。', 'A mechanism that re-executes a process from recorded inputs, events, or state.');
  term('persistence', 'resume', 'Resume', '恢复执行', '从暂停点或检查点继续未完成运行的操作。', 'The operation of continuing an unfinished run from a pause point or checkpoint.');
  term('langgraph', 'workflow', 'Workflow', '工作流', '由任务步骤、依赖关系和控制规则组成的执行过程。', 'An execution process composed of task steps, dependencies, and control rules.');
  term('langgraph', 'control-flow', 'Control Flow', '控制流', '决定执行步骤顺序、分支和循环的规则。', 'Rules determining the order, branches, and loops of execution steps.');
  term('langgraph', 'graph', 'Graph', '执行图', '以节点表示处理步骤、以边表示流转关系的执行结构。', 'An execution structure with nodes as processing steps and edges as transitions.');
  term('langgraph', 'node', 'Node', '节点', '执行图中执行计算、模型调用或工具操作的处理单元。', 'A processing unit in an execution graph that performs computation, model calls, or tool operations.');
  term('graphRecursion', 'superstep', 'Superstep', '超步', '图执行中的一轮推进；同一超步内的多个活跃节点可以并行运行，递归限制按超步计数。', 'One round of graph execution in which multiple active nodes may run in parallel; the recursion limit counts supersteps.');
  term('graphRecursion', 'graph-recursion-error', 'Graph Recursion Error', '图递归限制错误', '图在达到递归限制但尚未满足停止条件时产生的执行错误。', 'The execution error raised when a graph reaches its recursion limit before satisfying a stopping condition.', ['GraphRecursionError']);
  term('langgraph', 'edge', 'Edge', '边', '执行图中连接节点并表示流转方向的关系。', 'A relation connecting nodes and indicating transition direction in an execution graph.');
  term('langgraph', 'conditional-edge', 'Conditional Edge', '条件边', '依据运行时条件选择后续节点的图连接。', 'A graph connection that selects a next node according to a runtime condition.');
  term('langgraph', 'entry-point', 'Entry Point', '入口点', '图或工作流开始执行的节点或位置。', 'The node or location where graph or workflow execution begins.');
  term('langgraph', 'end-state', 'End State', '结束状态', '图或智能体运行完成时达到的终止状态。', 'A terminal state reached when a graph or agent run completes.');
  term('langgraph', 'branch', 'Branch', '分支', '控制流中可根据条件选择的不同执行路径。', 'An alternative execution path selected according to conditions in control flow.');
  term('langgraph', 'routing', 'Routing', '路由', '根据输入或状态选择后续模型、工具、节点或智能体的过程。', 'The process of selecting a next model, tool, node, or agent based on input or state.');
  term('multiagentWiki', 'multi-agent-system', 'Multi Agent System', '多智能体系统', '由多个相互交互的智能体组成的系统。', 'A system composed of multiple interacting agents.', ['MAS']);
  term('multiAgent', 'multi-agent-architecture', 'Multi Agent Architecture', '多智能体架构', '规定多个智能体的角色、通信和协调方式的系统结构。', 'A system structure defining roles, communication, and coordination among multiple agents.');
  term('multiAgent', 'agent-network', 'Agent Network', '智能体网络', '通过通信或任务关系连接的一组智能体。', 'A set of agents connected through communication or task relationships.');
  term('multiAgent', 'handoff', 'Handoff', '移交', '将当前对话或任务控制权转交给另一个智能体的机制。', 'A mechanism that transfers control of the current conversation or task to another agent.');
  term('multiAgent', 'centralized-coordination', 'Centralized Coordination', '集中式协调', '由一个中心智能体或控制器协调其他参与者的方式。', 'A mode in which one central agent or controller coordinates other participants.');
  term('multiAgent', 'decentralized-coordination', 'Decentralized Coordination', '分布式协调', '多个智能体在没有单一中心控制者的情况下协调行动的方式。', 'A mode in which agents coordinate actions without a single central controller.');
  term('multiAgent', 'cooperation', 'Cooperation', '协作', '多个智能体为共同目标共享信息或协调行动的行为。', 'Behavior in which multiple agents share information or coordinate actions toward a common goal.');
  term('multiAgent', 'competition', 'Competition', '竞争', '多个智能体追求可能冲突目标或有限资源的交互关系。', 'An interaction in which agents pursue potentially conflicting goals or limited resources.');
  term('multiAgent', 'coordination', 'Coordination', '协调', '组织多个智能体行动以管理依赖、冲突或共同目标的过程。', 'The process of organizing agent actions to manage dependencies, conflicts, or shared goals.');
  term('multiAgent', 'communication-protocol', 'Communication Protocol', '通信协议', '规定智能体之间消息格式、顺序和语义的约定。', 'A convention defining message formats, ordering, and meaning between agents.');
  term('multiAgent', 'shared-context', 'Shared Context', '共享上下文', '多个智能体能够共同访问的信息集合。', 'A set of information accessible to multiple agents.');
  term('multiAgent', 'context-isolation', 'Context Isolation', '上下文隔离', '限制一个智能体的上下文不被其他智能体自动访问的机制。', 'A mechanism preventing one agent\'s context from being automatically accessible to others.');
  term('multiAgent', 'role-specialization', 'Role Specialization', '角色专门化', '让不同智能体承担不同领域或功能职责的设计方式。', 'A design approach assigning different domain or functional responsibilities to different agents.');
  term('multiAgent', 'agent-selection', 'Agent Selection', '智能体选择', '依据任务或状态选择合适智能体处理工作的过程。', 'The process of selecting an appropriate agent for work based on a task or state.');
  term('multiAgent', 'agent-registry', 'Agent Registry', '智能体注册表', '记录可用智能体及其能力描述的目录。', 'A directory recording available agents and descriptions of their capabilities.');
  term('deepSkills', 'skill', 'Skill', '技能', '可供智能体按需使用的专项知识、指令或操作方法。', 'Specialized knowledge, instructions, or operating methods available to an agent on demand.');
  term('deepSkills', 'agent-skill', 'Agent Skill', '智能体技能', '供智能体按需加载和使用的专项知识或操作指令。', 'Specialized knowledge or operating instructions that an agent can load and use on demand.');
  term('deepSkills', 'skill-metadata', 'Skill Metadata', '技能元数据', '描述技能名称、用途、适用条件或其他属性的数据。', 'Data describing a skill\'s name, purpose, applicability, or other properties.');
  term('deepSkills', 'skill-discovery', 'Skill Discovery', '技能发现', '识别当前可用技能及其描述的过程。', 'The process of identifying currently available skills and their descriptions.');
  term('deepSkills', 'skill-loading', 'Skill Loading', '技能加载', '在需要时把技能内容加入智能体可用上下文的过程。', 'The process of adding skill content to agent-accessible context when needed.');
  term('interrupts', 'interrupt', 'Interrupt', '中断', '暂停执行并将控制权交给外部参与者或系统的事件。', 'An event that pauses execution and transfers control to an external participant or system.');
  term('interrupts', 'human-in-the-loop', 'Human in the Loop', '人在回路', '在自动化过程的关键步骤引入人工审查、输入或决策的设计。', 'A design that introduces human review, input, or decisions at key steps of an automated process.', ['HITL']);
  term('interrupts', 'approval-gate', 'Approval Gate', '审批门', '要求获得明确批准后才允许执行后续行动的控制点。', 'A control point requiring explicit approval before a subsequent action may execute.');
  term('interrupts', 'human-feedback', 'Human Feedback', '人工反馈', '由人类对模型或智能体输出、行为或偏好提供的评价信息。', 'Evaluative information provided by people about model or agent output, behavior, or preferences.');

  term('benchmark', 'evaluation', 'Evaluation', '评估', '使用标准、数据或人工判断衡量模型或智能体表现的过程。', 'The process of measuring model or agent performance using criteria, data, or human judgment.');
  term('benchmark', 'benchmark', 'Benchmark', '基准测试', '用于在统一条件下比较系统表现的任务、数据和指标集合。', 'A set of tasks, data, and metrics used to compare systems under common conditions.');
  term('benchmark', 'evaluation-dataset', 'Evaluation Dataset', '评估数据集', '用于测量模型或智能体表现的数据样本集合。', 'A collection of data samples used to measure model or agent performance.');
  term('benchmark', 'test-case', 'Test Case', '测试用例', '包含输入、条件和预期评价方式的单个评估实例。', 'A single evaluation instance containing input, conditions, and an expected assessment method.');
  term('benchmark', 'ground-truth', 'Ground Truth', '真实标注', '在评估中作为正确参考的已知标签、答案或事实。', 'A known label, answer, or fact used as a correctness reference in evaluation.');
  term('benchmark', 'reference-answer', 'Reference Answer', '参考答案', '用于与模型输出比较的预先提供答案。', 'A preprovided answer used for comparison with model output.');
  term('benchmark', 'metric', 'Metric', '指标', '用于量化系统某一表现维度的计算规则。', 'A calculation rule used to quantify one dimension of system performance.');
  term('benchmark', 'accuracy', 'Accuracy', '准确率', '预测结果中正确结果所占的比例。', 'The proportion of predictions that are correct.');
  term('benchmark', 'exact-match', 'Exact Match', '精确匹配', '要求预测与参考答案在规定归一化后完全一致的指标。', 'A metric requiring a prediction to exactly equal a reference after specified normalization.');
  term('benchmark', 'f1-score', 'F1 Score', 'F1 分数', '查准率与查全率调和平均得到的指标。', 'The harmonic mean of precision and recall.');
  term('benchmark', 'semantic-similarity', 'Semantic Similarity', '语义相似度', '衡量两段内容含义接近程度的指标或判断。', 'A metric or judgment of how close two pieces of content are in meaning.');
  term('benchmark', 'model-graded-evaluation', 'Model Graded Evaluation', '模型评分评估', '使用另一个模型对输出进行判断或打分的评估方法。', 'An evaluation method that uses another model to judge or score output.');
  term('benchmark', 'llm-as-judge', 'LLM as Judge', '大模型裁判', '使用大语言模型对其他模型输出进行判断、比较或评分的方法。', 'A method that uses a large language model to judge, compare, or score other model outputs.');
  term('benchmark', 'pairwise-evaluation', 'Pairwise Evaluation', '成对评估', '比较两个候选输出并选择更优者的评估方式。', 'An evaluation mode that compares two candidate outputs and selects the better one.');
  term('benchmark', 'pointwise-evaluation', 'Pointwise Evaluation', '逐点评估', '独立地对每个输出依据标准评分的评估方式。', 'An evaluation mode that scores each output independently against criteria.');
  term('benchmark', 'human-evaluation', 'Human Evaluation', '人工评估', '由人类评审者判断模型或智能体表现的评估方法。', 'An evaluation method in which human reviewers judge model or agent performance.');
  term('benchmark', 'online-evaluation', 'Online Evaluation', '在线评估', '在实际运行流量或交互中持续测量表现的评估。', 'Evaluation that continuously measures performance in live traffic or interactions.');
  term('benchmark', 'offline-evaluation', 'Offline Evaluation', '离线评估', '使用预先收集的数据在非实时环境中进行的评估。', 'Evaluation performed in a non-live environment using previously collected data.');
  term('benchmark', 'regression-evaluation', 'Regression Evaluation', '回归评估', '检查系统更新是否导致既有能力或指标退化的评估。', 'Evaluation checking whether system changes degrade existing capabilities or metrics.');
  term('benchmark', 'task-success-rate', 'Task Success Rate', '任务成功率', '达到预定义任务完成条件的运行比例。', 'The proportion of runs that satisfy predefined task-completion conditions.');
  term('benchmark', 'tool-call-accuracy', 'Tool Call Accuracy', '工具调用准确率', '工具选择及其参数符合预期的程度或比例。', 'The degree or proportion to which tool selection and arguments match expectations.');
  term('benchmark', 'trajectory-evaluation', 'Trajectory Evaluation', '轨迹评估', '对智能体完整步骤、行动和状态序列进行评价的方法。', 'An evaluation method assessing the complete sequence of agent steps, actions, and states.');
  term('benchmark', 'robustness', 'Robustness', '稳健性', '系统在输入变化、噪声或异常条件下维持表现的能力。', 'The ability of a system to maintain performance under input variation, noise, or unusual conditions.');
  term('benchmark', 'reliability', 'Reliability', '可靠性', '系统在规定条件下持续产生符合要求结果的能力。', 'The ability of a system to consistently produce acceptable results under specified conditions.');
  term('benchmark', 'determinism', 'Determinism', '确定性', '相同输入与状态总是产生相同结果的性质。', 'The property that identical input and state always produce the same result.');
  term('benchmark', 'reproducibility', 'Reproducibility', '可复现性', '在相同或明确条件下能够再次获得一致结果的程度。', 'The degree to which consistent results can be obtained again under the same or specified conditions.');
  term('benchmark', 'latency', 'Latency', '延迟', '从请求开始到产生指定响应或结果所经过的时间。', 'The elapsed time from the start of a request to a specified response or result.');
  term('benchmark', 'time-to-first-token', 'Time to First Token', '首词元时间', '从请求开始到收到首个输出词元的时间。', 'The time from request start until the first output token is received.', ['TTFT']);
  term('benchmark', 'throughput', 'Throughput', '吞吐量', '系统在单位时间内处理请求、词元或任务的数量。', 'The number of requests, tokens, or tasks a system processes per unit time.');
  term('benchmark', 'token-usage', 'Token Usage', '词元用量', '模型调用或运行所消耗输入与输出词元的数量。', 'The number of input and output tokens consumed by a model call or run.');
  term('benchmark', 'cost-per-run', 'Cost per Run', '单次运行成本', '完成一次模型或智能体运行所产生的计费成本。', 'The billed cost incurred by one model or agent run.');
  term('xai', 'observability', 'Observability', '可观测性', '通过外部输出理解系统内部执行状态与行为的能力。', 'The ability to understand internal execution state and behavior through external outputs.');
  term('xai', 'trace', 'Trace', '追踪记录', '一次请求或运行中跨步骤操作与时间关系的记录。', 'A record of operations and timing relationships across steps in one request or run.');
  term('xai', 'span', 'Span', '追踪跨度', '追踪中表示一个有起止时间操作的记录单元。', 'A trace unit representing an operation with a start and end time.');
  term('xai', 'run-tree', 'Run Tree', '运行树', '按父子关系组织嵌套模型、工具和链式调用的结构。', 'A structure organizing nested model, tool, and chained calls by parent-child relationships.');
  term('xai', 'telemetry', 'Telemetry', '遥测', '自动采集并传输系统运行指标、事件和追踪数据的过程。', 'The automatic collection and transmission of runtime metrics, events, and trace data.');
  term('xai', 'explainability', 'Explainability', '可解释性', '使人能够理解模型输出或系统决策原因的性质。', 'The property of enabling people to understand reasons behind model output or system decisions.');
  term('xai', 'interpretability', 'Interpretability', '可理解性', '模型内部机制或输入输出关系可被人理解的程度。', 'The degree to which a model\'s internal mechanisms or input-output relationships can be understood by people.');
  term('hallucination', 'hallucination', 'Hallucination', '幻觉', '模型生成貌似合理但缺乏输入或事实依据内容的现象。', 'The phenomenon of a model generating plausible-seeming content unsupported by input or facts.');
  term('hallucination', 'fabrication', 'Fabrication', '虚构', '模型生成不存在的事实、来源或细节的行为。', 'The production by a model of nonexistent facts, sources, or details.');
  term('hallucination', 'confabulation', 'Confabulation', '编造性补全', '模型在信息不足时以未经证实内容填补空缺的现象。', 'The tendency of a model to fill information gaps with unverified content.');
  term('aiSafety', 'guardrail', 'Guardrail', '护栏', '用于限制、检查或引导模型和智能体输入输出行为的控制机制。', 'A control mechanism that constrains, checks, or guides model and agent input-output behavior.');
  term('aiSafety', 'input-guardrail', 'Input Guardrail', '输入护栏', '在模型处理前检查或转换输入的安全与策略控制。', 'A safety and policy control that checks or transforms input before model processing.');
  term('aiSafety', 'output-guardrail', 'Output Guardrail', '输出护栏', '在结果交付前检查或转换模型输出的安全与策略控制。', 'A safety and policy control that checks or transforms model output before delivery.');
  term('aiSafety', 'content-moderation', 'Content Moderation', '内容审核', '识别并处理违反内容政策输入或输出的过程。', 'The process of identifying and handling input or output that violates content policies.');
  term('aiSafety', 'safety-filter', 'Safety Filter', '安全过滤器', '依据安全规则筛选、阻止或标记内容的机制。', 'A mechanism that filters, blocks, or flags content according to safety rules.');
  term('guardrails', 'prompt-injection', 'Prompt Injection', '提示注入', '通过输入内容诱导模型忽略或改变原有指令的攻击方式。', 'An attack that uses input content to induce a model to ignore or alter prior instructions.');
  term('owaspPromptInjection', 'direct-prompt-injection', 'Direct Prompt Injection', '直接提示注入', '攻击者直接在交互输入中放置恶意指令的提示注入。', 'Prompt injection in which an attacker places malicious instructions directly in interaction input.');
  term('indirectPromptInjection', 'indirect-prompt-injection', 'Indirect Prompt Injection', '间接提示注入', '恶意指令隐藏在模型检索或读取的外部内容中的提示注入。', 'Prompt injection in which malicious instructions are hidden in external content retrieved or read by a model.');
  term('aiSafety', 'jailbreak', 'Jailbreak', '越狱提示', '试图绕过模型安全约束或行为限制的输入策略。', 'An input strategy attempting to bypass model safety constraints or behavioral restrictions.');
  term('aiSafety', 'data-exfiltration', 'Data Exfiltration', '数据外泄', '未经授权将敏感或受保护数据传出其允许边界的行为。', 'The unauthorized transfer of sensitive or protected data beyond its permitted boundary.');
  term('aiSafety', 'least-privilege', 'Least Privilege', '最小权限', '仅授予完成任务所必需最少访问能力的安全原则。', 'The security principle of granting only the minimum access needed to perform a task.');
  term('aiSafety', 'sandboxing', 'Sandboxing', '沙箱隔离', '在受限制环境中执行代码或工具以控制其影响范围的机制。', 'A mechanism that executes code or tools in a restricted environment to limit their effects.');
  term('aiSafety', 'permission-boundary', 'Permission Boundary', '权限边界', '规定智能体或工具可以访问和修改哪些资源的限制。', 'A limit defining which resources an agent or tool may access and modify.');
  term('aiSafety', 'human-oversight', 'Human Oversight', '人工监督', '由人类监控、审查或干预人工智能系统行为的安排。', 'An arrangement in which people monitor, review, or intervene in AI system behavior.');
  term('aiSafety', 'safe-completion', 'Safe Completion', '安全完成', '在遵守安全限制的同时尽可能提供有帮助响应的方法。', 'A method of providing the most helpful response possible while respecting safety constraints.');
  term('aiSafety', 'refusal', 'Refusal', '拒绝响应', '模型因安全、政策或能力边界而不执行某项请求的响应。', 'A response in which a model declines a request because of safety, policy, or capability boundaries.');
  term('aiAlignment', 'alignment', 'Alignment', '对齐', '使人工智能系统行为与指定目标、价值或意图一致的问题与过程。', 'The problem and process of making AI system behavior consistent with specified goals, values, or intentions.');
  term('aiAlignment', 'outer-alignment', 'Outer Alignment', '外部对齐', '训练或评价目标是否正确表达期望价值与意图的问题。', 'The question of whether training or evaluation objectives correctly express desired values and intentions.');
  term('aiAlignment', 'inner-alignment', 'Inner Alignment', '内部对齐', '模型实际学到的目标是否与训练目标一致的问题。', 'The question of whether the objective learned by a model matches the training objective.');
  term('aiAlignment', 'reward-hacking', 'Reward Hacking', '奖励投机', '系统以非预期方式提高奖励指标而未实现真实目标的行为。', 'Behavior that increases a reward metric in unintended ways without achieving the true goal.');
  term('aiAlignment', 'specification-gaming', 'Specification Gaming', '规范投机', '系统利用目标规范漏洞获得表面成功的行为。', 'Behavior that exploits gaps in a specification to achieve superficial success.');

  term('ml', 'artificial-intelligence', 'Artificial Intelligence', '人工智能', '使计算系统表现出感知、推理、学习或行动能力的研究与技术领域。', 'The field of study and technology concerned with computational systems that exhibit perception, reasoning, learning, or action.', ['AI']);
  term('ml', 'machine-learning', 'Machine Learning', '机器学习', '使系统从数据中学习模式并改进任务表现的方法领域。', 'The field of methods that enable systems to learn patterns from data and improve task performance.', ['ML']);
  term('nlp', 'natural-language-processing', 'Natural Language Processing', '自然语言处理', '研究计算机处理、理解和生成人类语言的方法领域。', 'The field studying methods for computers to process, understand, and generate human language.', ['NLP']);
  term('transformer', 'transformer', 'Transformer', 'Transformer 架构', '主要依靠注意力机制处理序列关系的神经网络架构。', 'A neural-network architecture that relies primarily on attention mechanisms to process sequence relationships.');
  term('transformer', 'attention', 'Attention', '注意力机制', '根据输入元素相关性动态分配计算权重的机制。', 'A mechanism that dynamically assigns computational weight according to relevance among input elements.');
  term('transformer', 'self-attention', 'Self Attention', '自注意力', '在同一序列内部计算各元素相互关系的注意力机制。', 'An attention mechanism that computes relationships among elements within the same sequence.');
  term('transformer', 'multi-head-attention', 'Multi Head Attention', '多头注意力', '并行使用多个注意力表示子空间并合并结果的机制。', 'A mechanism that uses multiple attention representation subspaces in parallel and combines their results.');
  term('transformer', 'positional-encoding', 'Positional Encoding', '位置编码', '向序列表示加入元素位置信息的方法。', 'A method of adding element-position information to sequence representations.');
  term('ml', 'parameter', 'Model Parameter', '模型参数', '模型在训练中学习并用于计算输出的数值。', 'A numerical value learned during training and used by a model to compute output.');
  term('ml', 'model-weight', 'Model Weight', '模型权重', '神经网络中调节输入或中间表示影响程度的可学习参数。', 'A learnable neural-network parameter controlling the influence of input or intermediate representations.');
  term('ml', 'training', 'Training', '训练', '使用数据和优化方法调整模型参数的过程。', 'The process of adjusting model parameters using data and optimization methods.');
  term('ml', 'pretraining', 'Pretraining', '预训练', '在广泛数据和通用目标上先行训练模型的阶段。', 'The stage of first training a model on broad data and general objectives.');
  term('ml', 'fine-tuning', 'Fine Tuning', '微调', '在特定数据或目标上继续训练已有模型以调整其行为的过程。', 'The process of continuing training of an existing model on specific data or objectives to adapt its behavior.');
  term('ml', 'supervised-fine-tuning', 'Supervised Fine Tuning', '监督微调', '使用带有期望输出标注的样本微调模型的方法。', 'A method of fine-tuning a model with examples labeled with desired outputs.', ['SFT']);
  term('reinforcement', 'reinforcement-learning', 'Reinforcement Learning', '强化学习', '智能体通过行动、环境反馈和奖励学习策略的方法。', 'A method in which an agent learns a policy through actions, environmental feedback, and rewards.', ['RL']);
  term('reinforcement', 'reward-model', 'Reward Model', '奖励模型', '为候选行为或输出预测偏好或奖励分数的模型。', 'A model that predicts a preference or reward score for candidate behavior or output.');
  term('reinforcement', 'reward-signal', 'Reward Signal', '奖励信号', '用于评价行动结果并指导策略学习的数值反馈。', 'Numerical feedback used to evaluate action outcomes and guide policy learning.');
  term('reinforcement', 'policy', 'Policy', '策略', '将观察或状态映射为行动选择的规则或模型。', 'A rule or model mapping observations or states to action choices.');
  term('reinforcement', 'reinforcement-learning-from-human-feedback', 'Reinforcement Learning from Human Feedback', '基于人类反馈的强化学习', '利用人类偏好反馈构造奖励并优化模型行为的方法。', 'A method that uses human preference feedback to construct rewards and optimize model behavior.', ['RLHF']);
  term('reinforcement', 'direct-preference-optimization', 'Direct Preference Optimization', '直接偏好优化', '直接使用偏好成对数据优化模型而不显式训练奖励模型的方法。', 'A method that directly optimizes a model from pairwise preference data without explicitly training a reward model.', ['DPO']);
  term('ml', 'inference', 'Inference', '推理执行', '使用已训练模型根据输入计算预测或生成结果的过程。', 'The process of using a trained model to compute predictions or generated results from input.');
  term('ml', 'quantization', 'Quantization', '量化', '用较低精度数值表示模型参数或计算以降低资源需求的方法。', 'A method of representing model parameters or computation with lower-precision values to reduce resource requirements.');
  term('ml', 'knowledge-distillation', 'Knowledge Distillation', '知识蒸馏', '训练较小模型模仿较大模型行为或输出分布的方法。', 'A method of training a smaller model to imitate the behavior or output distribution of a larger model.');
  term('ml', 'mixture-of-experts', 'Mixture of Experts', '专家混合模型', '由多个专家子网络组成并按输入激活其中部分网络的模型结构。', 'A model structure composed of expert subnetworks that activates a subset according to input.', ['MoE']);
  term('ml', 'sparse-activation', 'Sparse Activation', '稀疏激活', '每次计算仅激活模型部分参数或组件的方式。', 'A mode in which only part of a model\'s parameters or components are active for each computation.');
  term('llm', 'emergent-ability', 'Emergent Ability', '涌现能力', '模型规模或训练变化后出现、在较小模型中不明显的能力。', 'A capability that appears after changes in model scale or training and is not evident in smaller models.');
  term('llm', 'scaling-law', 'Scaling Law', '缩放定律', '描述模型表现与参数、数据或计算规模之间经验关系的规律。', 'An empirical relationship between model performance and the scale of parameters, data, or computation.');
  term('models', 'model-capability', 'Model Capability', '模型能力', '模型能够完成的输入处理、生成、推理或工具使用功能。', 'An input-processing, generation, reasoning, or tool-use function a model can perform.');
  term('models', 'model-limitation', 'Model Limitation', '模型局限', '模型在能力、知识、可靠性或资源方面的约束。', 'A constraint on a model\'s capability, knowledge, reliability, or resources.');
  term('models', 'knowledge-cutoff', 'Knowledge Cutoff', '知识截止时间', '模型训练知识大致覆盖到的最晚时间边界。', 'The approximate latest time boundary covered by a model\'s training knowledge.');
  term('models', 'multimodality', 'Multimodality', '多模态能力', '处理或关联多种数据模态的能力。', 'The capability to process or relate multiple data modalities.');
  term('models', 'text-generation', 'Text Generation', '文本生成', '模型根据输入产生自然语言文本的任务。', 'The task of producing natural-language text from input with a model.');
  term('models', 'reasoning-effort', 'Reasoning Effort', '推理强度', '控制推理模型用于内部计算资源程度的设置概念。', 'A setting concept controlling the amount of internal computation used by a reasoning model.', ['reasoning_effort']);
  term('agents', 'synchronous-execution', 'Synchronous Execution', '同步执行', '调用方等待当前操作完成后再继续后续工作的执行方式。', 'An execution mode in which the caller waits for the current operation to finish before continuing.');
  term('agents', 'asynchronous-execution', 'Asynchronous Execution', '异步执行', '调用方无需阻塞等待当前操作完成的执行方式。', 'An execution mode in which the caller need not block while waiting for the current operation to finish.');
  term('agents', 'parallel-execution', 'Parallel Execution', '并行执行', '多个可独立工作单元在同一时间段同时推进的执行方式。', 'An execution mode in which multiple independent work units progress during the same time period.');
  term('agents', 'concurrent-execution', 'Concurrent Execution', '并发执行', '多个任务在时间上重叠推进、不要求物理同时运行的执行方式。', 'An execution mode in which multiple tasks make overlapping progress without requiring physical simultaneity.');
  term('multiAgent', 'nested-delegation', 'Nested Delegation', '嵌套委派', '被委派智能体继续把子任务委派给其他智能体的模式。', 'A pattern in which a delegated agent further delegates subtasks to other agents.');
  term('multiAgent', 'recursive-delegation', 'Recursive Delegation', '递归委派', '委派关系可沿多个层级重复发生的模式。', 'A pattern in which delegation may repeat across multiple levels.');
  term('multiAgent', 'dynamic-agent-selection', 'Dynamic Agent Selection', '动态智能体选择', '在运行时依据任务和状态选择智能体的机制。', 'A mechanism that selects an agent at runtime according to task and state.');
  term('multiAgent', 'static-agent-roster', 'Static Agent Roster', '静态智能体名册', '在运行开始前固定可用智能体集合的组织方式。', 'An organization mode in which the available agent set is fixed before execution begins.');
  term('context', 'context-schema', 'Context Schema', '上下文模式', '定义运行时上下文字段、类型和访问约定的模式。', 'A schema defining runtime-context fields, types, and access conventions.');
  term('context', 'model-surface', 'Model Surface', '模型可见表面', '一次请求中模型实际可见的提示、工具、模式和上下文集合。', 'The prompts, tools, schemas, and context actually visible to a model in a request.');
  term('mcp', 'model-context-protocol', 'Model Context Protocol', '模型上下文协议', '用于人工智能应用与外部工具和数据源交换上下文的开放协议。', 'An open protocol for AI applications to exchange context with external tools and data sources.', ['MCP']);
  term('mcp', 'mcp-client', 'MCP Client', 'MCP 客户端', '连接 MCP 服务器并发现或调用其能力的协议参与方。', 'A protocol participant that connects to MCP servers and discovers or invokes their capabilities.');
  term('mcp', 'mcp-server', 'MCP Server', 'MCP 服务器', '通过 MCP 向客户端公开工具、资源或提示的协议参与方。', 'A protocol participant that exposes tools, resources, or prompts to clients through MCP.');
  term('mcp', 'mcp-tool', 'MCP Tool', 'MCP 工具', 'MCP 服务器公开、可由客户端调用的操作。', 'An operation exposed by an MCP server for client invocation.');
  term('mcp', 'mcp-resource', 'MCP Resource', 'MCP 资源', 'MCP 服务器公开、可由客户端读取的上下文数据。', 'Contextual data exposed by an MCP server for clients to read.');
  term('mcp', 'mcp-prompt', 'MCP Prompt', 'MCP 提示', 'MCP 服务器公开、可由客户端获取的可复用提示模板。', 'A reusable prompt template exposed by an MCP server for clients to retrieve.');
  term('models', 'semantic-cache', 'Semantic Cache', '语义缓存', '依据输入语义相似性复用先前模型结果的缓存机制。', 'A cache mechanism that reuses prior model results based on semantic similarity of input.');
  term('models', 'exact-match-cache', 'Exact Match Cache', '精确匹配缓存', '仅在请求键完全匹配时复用先前模型结果的缓存机制。', 'A cache mechanism that reuses a prior model result only when request keys match exactly.');

  technologyTerm('deepagents', 'deep-agents-framework', 'Deep Agents', 'Deep Agents 智能体框架', '基于 LangChain、提供规划、文件系统、技能和子智能体能力的智能体框架。', 'An agent framework built on LangChain with planning, filesystem, skills, and subagent capabilities.', ['DeepAgents', 'deepagents']);
  technologyTerm('openaiModels', 'model-id', 'Model ID', '模型 ID', '在 API 或模型目录中唯一标识模型的字符串。', 'A string that uniquely identifies a model in an API or model catalog.');
  technologyTerm('openaiChat', 'assistant-role-value', 'assistant', '助手角色值', '聊天消息中表示内容由模型或助手生成的角色值。', 'The chat-message role value indicating content generated by a model or assistant.');
  technologyTerm('openaiChat', 'role-field', 'role', '消息角色字段', '聊天消息中标识消息来源或功能类别的字段。', 'The chat-message field identifying the source or functional category of a message.');
  technologyTerm('openaiChat', 'message-role-field', 'message.role', '消息角色字段路径', '指向聊天消息角色字段的限定字段路径。', 'The qualified field path referring to a chat message\'s role field.');
  technologyTerm('openaiChat', 'content-field', 'content', '消息内容字段', '聊天消息中承载文本或结构化内容的字段。', 'The chat-message field carrying text or structured content.');
  technologyTerm('openaiChat', 'message-content-field', 'message.content', '消息内容字段路径', '指向聊天消息内容字段的限定字段路径。', 'The qualified field path referring to a chat message\'s content field.');
  technologyTerm('openaiChat', 'stream-parameter', 'stream', '流式响应参数', '指定 API 是否以增量事件流返回响应的布尔参数。', 'The boolean parameter selecting whether an API returns its response as an incremental event stream.');
  technologyTerm('agentFactory', 'system-prompt-override', 'System Prompt Override', '系统提示覆写', '用新文本替换既有系统提示的配置字段。', 'A configuration field that replaces an existing system prompt with new text.', ['system_prompt_override']);
  technologyTerm('agentFactory', 'instruction-override', 'Instruction Override', '指令覆写', '用新文本替换既有智能体指令的配置字段。', 'A configuration field that replaces existing agent instructions with new text.', ['instruction_override']);
  technologyTerm('toolDefinition', 'tool-description-override', 'Tool Description Override', '工具说明覆写', '用新文本替换既有工具说明的配置字段。', 'A configuration field that replaces an existing tool description with new text.', ['tool_description_override']);
  technologyTerm('toolDefinition', 'description-override', 'Description Override', '说明覆写', '用新文本替换既有说明的配置字段。', 'A configuration field that replaces an existing description with new text.', ['description_override']);
  technologyTerm('toolDefinition', 'visible-field', 'visible', '可见性字段', '表示某项工具或能力是否出现在可用表面中的布尔字段。', 'A boolean field indicating whether a tool or capability appears in an available surface.');
  technologyTerm('models', 'max-tokens-parameter', 'Max Tokens', '最大词元数参数', '限制一次模型生成所产生词元数量的参数。', 'A parameter limiting the number of tokens produced by one model generation.');
  technologyTerm('models', 'seed-parameter', 'seed', '随机种子参数', '为模型采样过程提供随机种子值的参数。', 'A parameter supplying a random-seed value to a model sampling process.');
  technologyTerm('models', 'timeout-parameter', 'timeout', '超时参数', '限制一次模型请求最多等待时长的参数。', 'A parameter limiting how long a model request may wait.');
  technologyTerm('models', 'max-retries-parameter', 'Max Retries', '最大重试次数参数', '限制失败请求可以再次尝试次数的参数。', 'A parameter limiting how many times a failed request may be retried.');
  technologyTerm('streaming', 'stream-usage-parameter', 'Stream Usage', '流式用量参数', '指定流式响应是否附带词元用量统计的参数。', 'A parameter selecting whether a streamed response includes token-usage statistics.');
  technologyTerm('models', 'stop-parameter', 'stop', '停止序列参数', '指定一个或多个触发模型停止生成的文本序列的参数。', 'A parameter specifying one or more text sequences that stop model generation.');
  technologyTerm('models', 'logprobs-parameter', 'logprobs', '对数概率参数', '指定模型是否返回输出词元对数概率信息的参数。', 'A parameter selecting whether a model returns log-probability information for output tokens.');
  technologyTerm('models', 'top-logprobs-parameter', 'Top Logprobs', '最高对数概率参数', '指定每个输出位置返回多少个最高概率候选词元的参数。', 'A parameter specifying how many highest-probability token candidates are returned at each output position.');
  technologyTerm('tools', 'args-schema-parameter', 'Args Schema', '参数模式字段', '指定工具调用参数结构与验证规则的字段。', 'A field specifying the structure and validation rules of tool-call arguments.');
  technologyTerm('shortMemory', 'thread-id-field', 'Thread ID', '线程 ID', '唯一标识一条有状态执行线程或对话线程的字段。', 'A field uniquely identifying a stateful execution or conversation thread.');
  technologyTerm('agentFactory', 'create-agent-function', 'create_agent', '智能体创建函数', '把模型、工具、系统提示词和中间件组合成可运行智能体的 LangChain 工厂函数。', 'The LangChain factory function that composes a model, tools, a system prompt, and middleware into a runnable agent.');
  technologyTerm('agentFactory', 'qualified-create-agent-function', 'langchain.agents.create_agent', '智能体创建函数限定名', 'create_agent 在 langchain.agents 模块中的完全限定名称。', 'The fully qualified name of create_agent in the langchain.agents module.');
  technologyTerm('baseMessageApi', 'base-message-class', 'BaseMessage', '基础消息类', 'LangChain 各类消息对象共享的基础类型。', 'The common base type shared by LangChain message objects.');
  technologyTerm('modelRequestApi', 'model-request-class', 'ModelRequest', '模型请求对象', 'LangChain 在一次模型调用边界向中间件公开、可供读取或派生覆写的请求信息对象。', 'The LangChain request-information object exposed to middleware at one model-call boundary for inspection or derived overrides.');
  technologyTerm('modelResponseApi', 'model-response-class', 'ModelResponse', '模型响应对象', 'LangChain 对一次模型执行返回消息列表及可选结构化输出的响应封装。', 'The LangChain response wrapper for the message list and optional structured output returned by one model execution.');
  technologyTerm('modelRequestApi', 'model-request-override-method', 'ModelRequest.override()', '模型请求覆写方法', '返回替换指定属性的新 ModelRequest，并保持原请求对象不变的方法。', 'A method that returns a new ModelRequest with selected attributes replaced while leaving the original request unchanged.', ['request.override()']);
  technologyTerm('dynamicPromptMiddleware', 'model-request-system-message-field', 'ModelRequest.system_message', '模型请求系统消息字段', '在模型请求中单独承载 Agent SystemMessage 的字段；字符串 system prompt 也会转换为 SystemMessage。', 'The field that separately carries the agent SystemMessage in a model request; a string system prompt is also converted to a SystemMessage.');
  technologyTerm('modelRequestApi', 'model-request-messages-field', 'ModelRequest.messages', '模型请求消息列表字段', '模型请求中的当前消息列表；单独的 Agent SystemMessage 由 system_message 字段承载。', 'The current message list in a model request; the separate agent SystemMessage is carried by the system_message field.');
  technologyTerm('messages', 'content-blocks-property', 'content_blocks', '标准内容块属性', '把消息原始 content 延迟解析并公开为统一带类型内容块列表的消息属性。', 'A message property that lazily parses raw content and exposes it as a common list of typed content blocks.', ['BaseMessage.content_blocks']);
  technologyTerm('wrapModelCallApi', 'wrap-model-call-hook', 'wrap_model_call', '模型调用包裹钩子', '围绕每次模型调用运行、可检查或修改请求与响应并控制处理器调用次数的 LangChain 中间件钩子。', 'A LangChain middleware hook that runs around every model call, can inspect or modify requests and responses, and controls handler invocation count.');
  technologyTerm('customMiddleware', 'agent-middleware-class', 'AgentMiddleware', '智能体中间件基类', '用于声明智能体钩子、附加工具和状态扩展的 LangChain 中间件基类。', 'The LangChain base class for agent hooks, bundled tools, and state extensions.');
  technologyTerm('customMiddleware', 'custom-middleware', 'Custom Middleware', '自定义中间件', '由应用定义并插入智能体执行生命周期的中间件实现。', 'Application-defined middleware inserted into the agent execution lifecycle.');
  technologyTerm('toolDefinition', 'tool-decorator', '@tool', '工具装饰器', '把 Python 函数转换成 LangChain 工具，并默认使用函数文档字符串作为工具说明。', 'A decorator that converts a Python function into a LangChain tool and uses its docstring as the default description.');
  technologyTerm('toolDefinition', 'langchain-tool-qualified-name', 'langchain.tools.tool', '工具装饰器限定名', 'tool 装饰器在 langchain.tools 模块中的完全限定名称。', 'The fully qualified name of the tool decorator in the langchain.tools module.');
  technologyTerm('toolDefinition', 'langchain-core-tool-qualified-name', 'langchain_core.tools.tool', '核心工具装饰器限定名', 'tool 装饰器在 langchain_core.tools 模块中的完全限定名称。', 'The fully qualified name of the tool decorator in the langchain_core.tools module.');
  technologyTerm('baseTool', 'base-tool', 'Base Tool', '基础工具类', 'LangChain 可调用工具共享的基础接口类型。', 'The common base interface type for callable LangChain tools.', ['BaseTool']);
  technologyTerm('chatOpenAI', 'langchain-openai-package', 'langchain-openai', 'LangChain OpenAI 集成包', '为 OpenAI API 及兼容聊天端点提供 LangChain 模型适配的 Python 分发包。', 'The Python distribution that adapts OpenAI and compatible chat endpoints to LangChain model interfaces.');
  technologyTerm('chatOpenAI', 'langchain-openai-module', 'langchain_openai', 'LangChain OpenAI 模块', 'langchain-openai 分发包提供的 Python 导入模块。', 'The Python import module provided by the langchain-openai distribution.');
  technologyTerm('chatOpenAI', 'chat-openai', 'ChatOpenAI', 'ChatOpenAI 聊天模型', '面向 OpenAI Chat Completions 规范并支持自定义基础地址的 LangChain 聊天模型实现。', 'A LangChain chat-model implementation targeting the OpenAI Chat Completions specification and supporting a custom base URL.');
  technologyTerm('todoMiddleware', 'todo-list-middleware', 'TodoListMiddleware', '待办列表中间件', '为智能体注入任务规划提示词、写入待办工具和待办状态的中间件。', 'Middleware that adds planning instructions, a todo-writing tool, and todo state.');
  technologyTerm('todoMiddlewareApi', 'write-todos-tool', 'write_todos', '写入待办工具', '提交完整待办列表并替换当前待办状态的工具。', 'The tool that submits a complete todo list and replaces the current todo state.');
  technologyTerm('todoMiddlewareApi', 'todos-state', 'todos', '待办列表状态', 'TodoListMiddleware 在智能体状态中维护的结构化待办数组。', 'The structured todo array maintained in agent state by TodoListMiddleware.');
  technologyTerm('todoMiddlewareApi', 'todo-status', 'Todo Status', '待办状态值', '表示待办项所处处理阶段的字段。', 'The field indicating the processing stage of a todo item.');
  technologyTerm('todoMiddlewareApi', 'todo-status-pending', 'pending', '待处理状态', '表示待办项尚未开始处理的状态值。', 'The status value indicating that a todo item has not started.');
  technologyTerm('todoMiddlewareApi', 'todo-status-in-progress', 'in_progress', '进行中状态', '表示待办项正在处理的状态值。', 'The status value indicating that a todo item is in progress.');
  technologyTerm('todoMiddlewareApi', 'todo-status-completed', 'completed', '已完成状态', '表示待办项已经完成的状态值。', 'The status value indicating that a todo item is complete.');
  technologyTerm('todoMiddlewareApi', 'todo-item-content', 'todos[].content', '待办项内容字段', '描述待办项所代表任务的文本字段。', 'The text field describing the task represented by a todo item.');
  technologyTerm('modelRetryMiddleware', 'model-retry-middleware', 'ModelRetryMiddleware', '模型重试中间件', '模型调用失败时按配置自动重试的中间件。', 'Middleware that automatically retries failed model calls.');
  technologyTerm('retryMiddleware', 'tool-retry-middleware', 'ToolRetryMiddleware', '工具重试中间件', '工具调用失败时按配置自动重试的中间件。', 'Middleware that automatically retries failed tool calls.');
  technologyTerm('retryMiddleware', 'exponential-backoff', 'Exponential Backoff', '指数退避', '让连续重试的等待时间按指数增长的重试策略。', 'A retry strategy in which delays grow exponentially between attempts.', ['exponential_backoff']);
  technologyTerm('retryMiddleware', 'backoff-factor', 'Backoff Factor', '退避倍率', '控制连续重试等待时间增长倍率的参数。', 'The parameter controlling how retry delays grow between attempts.', ['backoff_factor']);
  technologyTerm('retryMiddleware', 'initial-retry-delay', 'initial_delay', '初始重试延迟', '第一次重试前等待时长的参数。', 'The parameter defining the delay before the first retry.');
  technologyTerm('piiMiddleware', 'pii-middleware', 'PIIMiddleware', '个人身份信息中间件', '检测并按策略处理消息中个人身份信息的中间件。', 'Middleware that detects and handles personally identifiable information in messages.');
  technologyTerm('piiMiddleware', 'personally-identifiable-information', 'Personally Identifiable Information', '个人身份信息', '能够直接或间接识别个人的数据。', 'Data that can directly or indirectly identify an individual.', ['PII', 'personally-identifiable information']);
  technologyTerm('piiMiddleware', 'pii-detection-configuration', 'PII Detection Configuration', 'PII 检测配置', '指定检测类型、处理策略以及检测应用位置的一组参数。', 'Parameters selecting the PII type, handling strategy, and where detection applies.');
  technologyTerm('piiMiddleware', 'pii-type-parameter', 'pii_type', 'PII 类型参数', '指定需要检测的个人身份信息类别的参数。', 'The parameter specifying the category of personally identifiable information to detect.');
  technologyTerm('piiMiddleware', 'pii-strategy-parameter', 'strategy', 'PII 处理策略参数', '指定检测到个人身份信息后所采用处理方式的参数。', 'The parameter selecting how detected personally identifiable information is handled.');
  technologyTerm('piiMiddleware', 'apply-to-input-parameter', 'apply_to_input', '输入检测开关', '指定是否对进入模型的消息应用个人身份信息检测的布尔参数。', 'The boolean parameter selecting whether PII detection applies to messages entering the model.');
  technologyTerm('piiMiddleware', 'redact-strategy', 'redact', '遮盖策略值', '用遮盖文本替换检测到的个人身份信息的处理策略值。', 'The strategy value that replaces detected personally identifiable information with redacted text.');
  technologyTerm('callLimitMiddleware', 'model-call-limit-middleware', 'ModelCallLimitMiddleware', '模型调用限制中间件', '限制一次运行中模型调用次数的中间件。', 'Middleware that limits model calls during a run.');
  technologyTerm('callLimitMiddleware', 'tool-call-limit-middleware', 'ToolCallLimitMiddleware', '工具调用限制中间件', '限制一次运行中工具调用次数的中间件。', 'Middleware that limits tool calls during a run.');
  technologyTerm('callLimitMiddleware', 'run-limit', 'Run Limit', '单次运行限制', '一次智能体调用内允许的模型或工具调用次数上限。', 'The maximum number of model or tool calls allowed in one agent invocation.', ['run_limit']);
  technologyTerm('callLimitMiddleware', 'limit-exit-behavior', 'Exit Behavior', '达限退出行为', '达到调用上限后结束、继续或报错的处理方式。', 'The behavior used after a call limit is reached, such as ending, continuing, or raising an error.', ['exit_behavior']);
  technologyTerm('callLimitMiddleware', 'exit-behavior-end', 'exit_behavior=end', '达限结束值', '达到调用上限后结束智能体运行的退出行为值。', 'The exit-behavior value that ends the agent run when a call limit is reached.');
  technologyTerm('callLimitMiddleware', 'exit-behavior-continue', 'exit_behavior=continue', '达限继续值', '达到调用上限后移除受限调用能力并继续运行的退出行为值。', 'The exit-behavior value that continues the run without the limited calling capability.');
  technologyTerm('toolSelectorMiddleware', 'llm-tool-selector-middleware', 'LLMToolSelectorMiddleware', 'LLM 工具选择中间件', '先用模型和结构化输出筛选相关工具，再执行主模型调用的中间件。', 'Middleware that uses an LLM and structured output to select relevant tools before the main model call.');
  technologyTerm('toolSelectorMiddleware', 'maximum-selected-tools', 'max_tools', '最大入选工具数', '工具选择器最多保留工具数量的参数。', 'The parameter limiting how many tools the tool selector retains.');
  technologyTerm('contextEditingMiddleware', 'context-editing-middleware', 'ContextEditingMiddleware', '上下文编辑中间件', '按编辑策略清理旧工具结果以控制上下文大小的中间件。', 'Middleware that applies edit strategies to clear old tool results and control context size.');
  technologyTerm('contextEditingMiddleware', 'context-edits', 'edits', '上下文编辑策略列表', 'ContextEditingMiddleware 按顺序应用的一组上下文编辑策略。', 'The collection of context-edit strategies applied by ContextEditingMiddleware.');
  technologyTerm('contextEditingMiddleware', 'clear-tool-uses-edit', 'ClearToolUsesEdit', '工具使用清理编辑器', '超过阈值后清除较旧工具结果并保留最近结果的上下文编辑策略。', 'A context-edit strategy that clears older tool results after a threshold while preserving recent results.');
  technologyTerm('contextEditingMiddleware', 'context-edit-trigger', 'ClearToolUsesEdit.trigger', '上下文编辑触发阈值', '触发工具结果清理的词元数量阈值参数。', 'The token-count threshold parameter that triggers context editing.');
  technologyTerm('contextEditingMiddleware', 'tool-results-to-keep', 'ClearToolUsesEdit.keep', '保留的工具结果数', '上下文编辑时保留最近工具结果数量的参数。', 'The parameter defining how many recent tool results remain during context editing.');

  technologyTerm('deepBackends', 'filesystem-backend-interface', 'Backend', '文件后端接口', '文件工具用来读取、写入和检索数据的可插拔存储接口。', 'The pluggable storage interface used by filesystem tools to read, write, and search data.');
  technologyTerm('deepBackends', 'backend-protocol', 'BackendProtocol', '文件后端协议', 'Deep Agents 文件后端实现读取、写入、编辑和检索操作时遵循的接口协议。', 'The interface protocol implemented by Deep Agents filesystem backends for read, write, edit, and search operations.');
  technologyTerm('deepBackends', 'composite-backend', 'Composite Backend', '组合后端', '按虚拟路径把文件操作路由到不同后端，并用默认后端处理未匹配路径。', 'A backend that routes virtual paths to different backends and sends unmatched paths to a default backend.', ['CompositeBackend', 'composite_backend']);
  technologyTerm('deepBackends', 'state-backend', 'State Backend', '状态后端', '把文件保存在当前 LangGraph 线程状态中的后端。', 'A backend that stores files in the current LangGraph thread state.', ['StateBackend', 'state_backend']);
  technologyTerm('deepBackends', 'filesystem-backend', 'Filesystem Backend', '文件系统后端', '直接操作本地磁盘，并以配置的根目录作为相对路径解析基准的后端；启用虚拟路径模式时，访问会被限制在该根目录内。', 'A backend that operates on local disk and uses a configured root directory to resolve relative paths; virtual mode confines access beneath that root.', ['FilesystemBackend', 'filesystem_backend']);
  technologyTerm('deepFilesystem', 'filesystem-middleware', 'Filesystem Middleware', '文件系统中间件', '向智能体提供文件读取、写入、编辑、检索和大结果卸载能力的中间件。', 'Middleware that exposes file reading, writing, editing, search, and large-result offloading to an agent.', ['FilesystemMiddleware', 'filesystem_middleware']);
  technologyTerm('deepBackends', 'backend-route', 'Backend Route', '后端路由', 'CompositeBackend 将匹配指定路径前缀的文件操作委派给特定后端的路由。', 'A CompositeBackend route that delegates file operations matching a path prefix to a specific backend.');
  technologyTerm('deepBackends', 'routes-parameter', 'routes', '后端路由参数', '按路径前缀将文件操作映射到指定后端的 CompositeBackend 构造参数。', 'The CompositeBackend constructor parameter mapping path prefixes to specific backends.');
  technologyTerm('deepBackends', 'mapped-directories-parameter', 'mapped_directories', '映射目录参数', '描述虚拟目录与磁盘目录之间映射关系的配置参数。', 'A configuration parameter describing mappings between virtual directories and disk directories.');
  technologyTerm('deepBackends', 'default-backend', 'Default Backend', '默认后端', 'CompositeBackend 在没有路由匹配时使用的后端。', 'The backend used by CompositeBackend when no route matches.', ['default_backend']);
  technologyTerm('deepBackends', 'default-parameter', 'default', '默认后端参数', '指定 CompositeBackend 未匹配路由时所用后端的构造参数。', 'The constructor parameter specifying the backend used by CompositeBackend when no route matches.');
  technologyTerm('deepBackends', 'root-directory', 'Root Directory', '根目录', 'FilesystemBackend 解析相对路径时使用的基准目录；是否同时构成访问边界取决于虚拟路径模式。', 'The base directory used by FilesystemBackend to resolve relative paths; whether it also forms an access boundary depends on virtual mode.');
  technologyTerm('deepBackends', 'root-dir-parameter', 'root_dir', '根目录参数', '指定 FilesystemBackend 解析相对路径所用基准目录的参数。', 'The parameter specifying the base directory FilesystemBackend uses to resolve relative paths.');
  technologyTerm('deepBackends', 'local-path-parameter', 'local_path', '本地路径参数', '指向本地文件或目录位置的路径参数。', 'A path parameter referring to a local file or directory location.');
  technologyTerm('deepBackends', 'virtual-mode', 'Virtual Mode', '虚拟路径模式', '将路径规范化并限制在 FilesystemBackend 根目录内的模式。', 'A filesystem-backend mode that normalizes paths and confines them beneath its root directory.', ['virtual_mode', 'virtual mode']);
  technologyTerm('deepagents', 'virtual-filesystem', 'Virtual Filesystem', '虚拟文件系统', '智能体通过绝对虚拟路径访问、可由不同后端承载的文件空间。', 'A file space accessed by an agent through absolute virtual paths and backed by pluggable backends.', ['virtual filesystem', 'virtual file system', 'VFS']);
  technologyTerm('deepBackends', 'virtual-path', 'Virtual Path', '虚拟路径', '智能体在虚拟文件系统中用于定位文件或目录的绝对路径。', 'An absolute path used by an agent to locate a file or directory in its virtual filesystem.', ['virtual_path']);
  technologyTerm('deepBackends', 'file-data', 'FileData', '文件数据', 'Deep Agents 文件后端用于表示文件内容、编码以及可选创建和修改时间的数据结构。', 'The data structure used by Deep Agents filesystem backends to represent file content, encoding, and optional creation and modification timestamps.', ['file data']);
  technologyTerm('deepSkills', 'create-file-data', 'create_file_data', '文件数据创建函数', '把文件内容转换为 Deep Agents FileData 对象的辅助函数。', 'A Deep Agents helper that converts file content into a FileData object.', ['create file data']);
  technologyTerm('deepSkills', 'preloaded-files', 'Preloaded Files', '预加载文件', '在智能体执行前提供给虚拟文件系统、供技能等能力读取的文件集合。', 'Files supplied to a virtual filesystem before agent execution so capabilities such as skills can read them.');
  technologyTerm('deepSkills', 'initial-files-parameter', 'initial_files', '初始文件参数', '表示虚拟文件系统初始文件集合的参数。', 'A parameter representing the initial collection of files in a virtual filesystem.');
  technologyTerm('deepSkills', 'virtual-files-parameter', 'virtual_files', '虚拟文件参数', '描述需要写入指定虚拟路径的文件集合的参数。', 'A parameter describing files to be written at specified virtual paths.');
  technologyTerm('deepSkills', 'virtual-directories-parameter', 'virtual_directories', '虚拟目录参数', '描述需要导入虚拟文件系统的目录集合的参数。', 'A parameter describing directories to import into a virtual filesystem.');
  technologyTerm('deepSkills', 'source-path-parameter', 'source_path', '来源路径参数', '指定文件或目录内容来源位置的路径参数。', 'A path parameter specifying the source location of file or directory content.');
  technologyTerm('deepFilesystem', 'custom-tool-descriptions', 'Custom Tool Descriptions', '自定义工具说明', '按工具名替换文件工具说明的构造参数映射。', 'A constructor mapping that replaces filesystem-tool descriptions by tool name.', ['custom_tool_descriptions']);
  technologyTerm('deepFilesystem', 'tool-configs-parameter', 'tool_configs', '工具配置参数', '按工具名组织可见性和说明等设置的配置映射。', 'A configuration mapping that organizes settings such as visibility and descriptions by tool name.');
  technologyTerm('deepFilesystem', 'tool-token-limit-before-evict', 'Tool Token Limit Before Evict', '工具结果卸载前词元阈值', '工具结果超过该词元阈值时将完整结果卸载到后端，并以预览和路径替代。', 'The token threshold above which a complete tool result is offloaded to the backend and replaced by a preview and path.', ['tool_token_limit_before_evict']);
  technologyTerm('deepagents', 'tool-result-offloading', 'Tool Result Offloading', '工具结果卸载', '把过大的工具结果保存到文件空间以避免其持续占用模型上下文。', 'Storing oversized tool results in the filesystem so they do not continue occupying model context.');
  technologyTerm('deepBackends', 'large-tool-results', 'Large Tool Results', '大型工具结果', 'Deep Agents 保存已卸载大型工具结果的内部文件命名空间。', 'The internal filesystem namespace used by Deep Agents for offloaded large tool results.', ['large_tool_results']);
  technologyTerm('deepBackends', 'large-tool-results-path', '/large_tool_results/', '大型工具结果路径', 'Deep Agents 用于保存已卸载大型工具结果的虚拟文件系统路径。', 'The virtual-filesystem path used by Deep Agents for offloaded large tool results.');
  technologyTerm('deepBackends', 'conversation-history-files', 'Conversation History Files', '会话历史文件', 'Deep Agents 保存从模型上下文移出的会话历史的内部文件空间。', 'The internal file space used by Deep Agents for conversation history moved out of model context.');
  technologyTerm('deepBackends', 'conversation-history-namespace', 'conversation_history', '会话历史命名空间', 'Deep Agents 用于保存从模型上下文移出会话历史的内部命名空间。', 'The internal namespace used by Deep Agents for conversation history moved out of model context.');
  technologyTerm('deepBackends', 'conversation-history-path', '/conversation_history/', '会话历史路径', 'Deep Agents 会话历史内部命名空间的虚拟文件系统路径。', 'The virtual-filesystem path of the Deep Agents internal conversation-history namespace.');
  technologyTerm('deepBackends', 'ls-tool', 'ls', '列目录工具', '列出指定绝对目录中的文件和目录。', 'A tool that lists files and directories under a specified absolute directory.');
  technologyTerm('deepBackends', 'read-file-tool', 'read_file', '读取文件工具', '读取文件内容，并可用起始偏移量和行数上限分页。', 'A tool that reads file content with optional offset-and-limit pagination.');
  technologyTerm('deepBackends', 'write-file-tool', 'write_file', '写入文件工具', '创建新文件或向目标文件写入内容。', 'A tool that creates a file or writes content to a target file.');
  technologyTerm('deepBackends', 'edit-file-tool', 'edit_file', '编辑文件工具', '通过精确字符串匹配替换已有文件内容。', 'A tool that edits an existing file through exact string replacement.');
  technologyTerm('deepBackends', 'glob-tool', 'glob', '文件模式查找工具', '按 Glob 模式查找匹配的文件路径。', 'A tool that finds file paths matching a glob pattern.');
  technologyTerm('deepBackends', 'grep-tool', 'grep', '文件内容检索工具', '在文件中搜索字面文本并返回文件、匹配内容或计数。', 'A tool that searches files for literal text and returns files, matching content, or counts.');
  technologyTerm('deepBackends', 'execute-tool', 'execute', '命令执行工具', '在支持执行的文件后端中运行 shell 命令的工具。', 'A tool that runs shell commands on execution-capable filesystem backends.');
  technologyTerm('deepBackends', 'sandbox-backend-protocol', 'Sandbox Backend Protocol', '沙箱后端协议', '文件后端为提供命令执行工具而实现的沙箱执行协议。', 'The sandbox execution protocol a filesystem backend implements to provide command execution.', ['SandboxBackendProtocol', 'sandbox backend protocol']);
  technologyTerm('deepagents', 'absolute-path', 'Absolute Path', '绝对路径', '从虚拟文件系统根开始并以斜杠开头的完整路径。', 'A complete path beginning at the virtual-filesystem root with a slash.');
  technologyTerm('deepBackends', 'file-path-parameter', 'file_path', '文件路径参数', '指定文件工具所操作文件或目录位置的路径参数。', 'The path parameter specifying the file or directory operated on by a filesystem tool.');
  technologyTerm('deepFilesystem', 'read-offset', 'offset', '起始偏移量', 'read_file 开始读取内容的位置偏移参数。', 'The offset parameter selecting where read_file begins reading content.');
  technologyTerm('deepBackends', 'read-limit', 'limit', '读取行数上限', 'read_file 一次最多读取源文件行数的参数。', 'The parameter limiting how many source lines one read_file call reads.');
  technologyTerm('deepBackends', 'exact-string-replacement', 'Exact String Replacement', '精确字符串替换', '用新文本替换文件中完全匹配的旧文本，并可选择替换全部匹配项。', 'Replacing exactly matching old text with new text, optionally replacing every occurrence.');
  technologyTerm('deepBackends', 'old-string-parameter', 'old_string', '旧字符串参数', '指定编辑操作需要精确匹配并替换的原文本。', 'The parameter specifying the original text that an edit operation must match exactly.');
  technologyTerm('deepBackends', 'new-string-parameter', 'new_string', '新字符串参数', '指定编辑操作用于替换原文本的新文本。', 'The parameter specifying the new text that replaces the matched original text.');
  technologyTerm('deepBackends', 'replace-all-parameter', 'replace_all', '全部替换参数', '指定编辑操作是否替换全部匹配项的布尔参数。', 'The boolean parameter selecting whether an edit operation replaces every match.');
  technologyTerm('deepBackends', 'glob-pattern', 'Glob Pattern', 'Glob 匹配模式', '使用星号、双星号和问号等通配符匹配文件路径的模式。', 'A file-path matching pattern using wildcards such as asterisks and question marks.');
  technologyTerm('deepBackends', 'glob-pattern-parameter', 'glob.pattern', 'Glob 模式参数', 'glob 工具用于指定文件路径匹配模式的输入字段。', 'The input field specifying the file-path matching pattern used by the glob tool.');
  technologyTerm('deepFilesystem', 'grep-search-pattern', 'Grep Search Pattern', 'Grep 搜索模式', 'grep 工具用于在文件内容中查找字面文本的输入参数。', 'The input parameter containing literal text for the grep tool to find in file contents.');
  technologyTerm('deepFilesystem', 'grep-pattern-parameter', 'grep.pattern', 'Grep 模式参数', 'grep 工具用于指定字面搜索文本的输入字段。', 'The input field specifying the literal search text used by the grep tool.');
  technologyTerm('deepFilesystem', 'grep-output-mode', 'Grep Output Mode', 'Grep 输出模式', '控制 grep 返回匹配文件、匹配内容或匹配计数的参数。', 'A parameter controlling whether grep returns matching files, matching content, or match counts.');
  technologyTerm('deepFilesystem', 'output-mode-parameter', 'output_mode', '输出模式参数', '指定 grep 返回匹配文件、匹配内容或匹配计数的参数。', 'The parameter selecting whether grep returns matching files, matching content, or match counts.');
  technologyTerm('deepFilesystem', 'files-with-matches-value', 'files_with_matches', '匹配文件输出值', '使 grep 仅返回包含匹配内容文件的输出模式值。', 'The output-mode value that makes grep return only files containing matches.');
  technologyTerm('deepFilesystem', 'output-mode-content-value', 'output_mode=content', '匹配内容输出值', '使 grep 返回匹配内容的输出模式赋值。', 'The output-mode assignment that makes grep return matching content.');
  technologyTerm('deepFilesystem', 'output-mode-count-value', 'output_mode=count', '匹配计数输出值', '使 grep 返回匹配计数的输出模式赋值。', 'The output-mode assignment that makes grep return match counts.');
  technologyTerm('deepSkills', 'skill-file', 'SKILL.md', '技能说明文件', '包含 YAML 前置元数据和按需加载技能指令的标准 Markdown 文件。', 'The standard Markdown file containing YAML frontmatter and on-demand skill instructions.');
  technologyTerm('deepSkills', 'skill-file-concept', 'Skill File', '技能文件', '保存可复用技能元数据和指令的文件。', 'A file containing reusable skill metadata and instructions.');
  technologyTerm('deepSkills', 'yaml-frontmatter', 'YAML Frontmatter', 'YAML 前置元数据', '位于 Markdown 文件开头、用于声明结构化元数据的 YAML 区块。', 'A YAML block at the start of a Markdown file declaring structured metadata.', ['YAML front matter']);
  technologyTerm('deepSkills', 'frontmatter', 'Frontmatter', '前置元数据', '位于文档开头并与正文分隔的结构化元数据区块。', 'A structured metadata block placed at the beginning of a document and separated from its body.');
  technologyTerm('deepSkills', 'skill-source', 'Skill Source', '技能来源路径', 'SkillsMiddleware 扫描并加载技能的后端目录路径。', 'A backend directory path scanned and loaded by SkillsMiddleware.');
  technologyTerm('deepSkillsApi', 'sources-parameter', 'sources', '技能来源参数', '指定 SkillsMiddleware 扫描哪些后端目录以发现技能的参数。', 'The parameter specifying which backend directories SkillsMiddleware scans to discover skills.');
  technologyTerm('deepSkills', 'allowed-tools-declaration', 'Allowed Tools', '允许工具声明', '技能前置元数据中提示该技能预期使用哪些工具的实验性字段，不会自行改变真实工具列表。', 'An experimental skill-frontmatter field indicating expected tools without itself changing the actual tool list.', ['allowed-tools', 'allowed_tools']);
  technologyTerm('deepSkillsApi', 'skill-prompt-placeholders', 'Skill Prompt Placeholders', '技能提示词占位符', 'SkillsMiddleware 渲染技能位置、加载警告和技能列表时使用的格式占位符集合。', 'The set of format placeholders used by SkillsMiddleware to render skill locations, loading warnings, and the skill list.');
  technologyTerm('deepSkillsApi', 'skills-locations-placeholder', '{skills_locations}', '技能位置占位符', '渲染可用技能来源位置的 SkillsMiddleware 格式占位符。', 'The SkillsMiddleware format placeholder for rendering available skill-source locations.');
  technologyTerm('deepSkillsApi', 'skills-load-warnings-placeholder', '{skills_load_warnings}', '技能加载警告占位符', '渲染技能加载警告的 SkillsMiddleware 格式占位符。', 'The SkillsMiddleware format placeholder for rendering skill-loading warnings.');
  technologyTerm('deepSkillsApi', 'skills-list-placeholder', '{skills_list}', '技能列表占位符', '渲染可用技能列表的 SkillsMiddleware 格式占位符。', 'The SkillsMiddleware format placeholder for rendering the available skill list.');
  technologyTerm('deepagents', 'ephemeral-subagent', 'Ephemeral Subagent', '临时子智能体', '为一次委派临时创建、在独立上下文中执行并在返回结果后结束的子智能体。', 'A subagent created for one delegation, executed in an isolated context, and ended after returning its result.');
  technologyTerm('deepSubagents', 'subagent-dictionary-spec', 'SubAgent', '子智能体字典规范', 'Deep Agents 用名称、说明、系统提示和可选工具等字段声明自定义同步子智能体的字典规范。', 'The Deep Agents dictionary specification for declaring a custom synchronous subagent with fields such as name, description, system prompt, and optional tools.');
  technologyTerm('compiledSubagentApi', 'compiled-subagent', 'CompiledSubAgent', '已编译子智能体', '以名称、说明和已编译 LangGraph Runnable 声明复杂自定义子智能体的 Deep Agents 规范。', 'The Deep Agents specification for a complex custom subagent defined by a name, description, and compiled LangGraph Runnable.');
  technologyTerm('deepSubagents', 'general-purpose-subagent', 'General-Purpose Subagent', '通用子智能体', 'Deep Agents 提供的默认同步子智能体，用于处理未分配给专用子智能体的一般任务。', 'The default synchronous subagent provided by Deep Agents for general tasks not assigned to a specialized subagent.', ['general-purpose']);
  technologyTerm('runnableApi', 'runnable-interface', 'Runnable', '可运行对象', 'LangChain 中可被调用、批处理、流式执行或组合的工作单元接口。', 'The LangChain interface for a work unit that can be invoked, batched, streamed, or composed.');
  technologyTerm('deepSubagents', 'task-tool', 'task', '子智能体任务工具', '主智能体用于启动同步子智能体并等待单个最终结果的工具。', 'The tool through which a main agent launches a synchronous subagent and waits for one final result.');
  technologyTerm('subagentMiddlewareApi', 'task-tool-input-description', 'task.description', '任务工具输入说明', '传给子智能体、用于说明任务上下文和期望输出的文本参数。', 'A text parameter passed to a subagent to describe the task context and expected output.');
  technologyTerm('deepCustomization', 'task-description', 'Task Description', '任务工具说明', 'SubAgentMiddleware 用于替换 task 工具说明的构造参数。', 'The SubAgentMiddleware constructor parameter that replaces the task tool description.', ['task_description']);
  technologyTerm('deepCustomization', 'available-agents-placeholder', '{available_agents}', '可用智能体占位符', '任务说明中在运行时替换为可用子智能体名称和说明列表的占位符。', 'A task-description placeholder replaced at runtime with available subagent names and descriptions.');
  technologyTerm('deepCustomization', 'available-agents-field', 'available_agents', '可用智能体字段', '承载可用子智能体名称和说明列表的字段。', 'A field carrying the names and descriptions of available subagents.');
  technologyTerm('deepSubagents', 'subagent-type', 'Subagent Type', '子智能体类型', 'task 工具中选择要调用哪一种子智能体的参数。', 'The task-tool parameter selecting which subagent type to invoke.', ['subagent_type']);

  technologyTerm('openaiOverview', 'openai-api', 'OpenAI API', 'OpenAI 接口', '由版本化 HTTP 端点、请求响应模式和流式行为组成的 OpenAI 接口。', 'The OpenAI versioned HTTP interface of endpoints, request-response schemas, and streaming behavior.');
  technologyTerm('openaiOverview', 'credential', 'Credential', '凭据', '用于证明 API 调用方身份的秘密、密钥或访问令牌。', 'A secret, key, or access token used to authenticate an API caller.');
  technologyTerm('openaiOverview', 'openai-rest-api', 'OpenAI REST API', 'OpenAI REST 接口', '通过 REST 风格 HTTP 端点公开的 OpenAI API。', 'The OpenAI API exposed through REST-style HTTP endpoints.');
  technologyTerm('chatOpenAI', 'openai-compatible-api', 'OpenAI-Compatible API', 'OpenAI 兼容接口', '采用可由 OpenAI API 客户端使用的端点与数据格式的接口；具体兼容范围由实现决定。', 'An API using endpoints and data formats consumable by OpenAI API clients; the exact compatibility surface is implementation-defined.', ['openai compatible api']);
  technologyTerm('agentShellSystemManagement', 'agent-shell-api-path-prefix', '/agent-shell/api', 'Agent Shell API 路径前缀', '当前实例中由 Agent Shell 拥有的管理与配置接口共同使用的路径前缀。', 'The path prefix shared by management and configuration endpoints owned by Agent Shell in the current instance.');
  technologyTerm('agentShellSystemManagement', 'openai-compatible-path-prefix', '/compat/openai/v1', 'OpenAI 兼容路径前缀', '当前实例中 OpenAI-compatible 接口使用的路径前缀；其中 v1 来自兼容目标的 wire contract。', 'The path prefix used by the current instance\'s OpenAI-compatible surface; v1 belongs to the target wire contract.');
  technologyTerm('openaiOverview', 'rest-api-v1', 'REST API v1', 'REST API v1', '使用 /v1 路径前缀的一组版本化 REST 接口。', 'A versioned REST interface using the /v1 path prefix.');
  technologyTerm('openaiOverview', 'v1-path-prefix', '/v1', 'v1 路径前缀', 'OpenAI API 版本一端点共用的 URL 路径前缀。', 'The URL path prefix shared by version-one OpenAI API endpoints.');
  technologyTerm('openaiOverview', 'api-endpoint', 'API Endpoint', 'API 端点', '由 HTTP 方法和路径标识的一项 API 操作。', 'An API operation identified by an HTTP method and path.');
  technologyTerm('openaiOverview', 'endpoint', 'Endpoint', '端点', '由网络地址以及可选方法标识的服务操作入口。', 'An entry point to a service identified by a network address and, optionally, a method.');
  technologyTerm('openaiOverview', 'api-base-url', 'API Base URL', 'API 基础地址', '所有版本化 API 端点共享的地址前缀。', 'The common address prefix shared by versioned API endpoints.', ['api_base_url']);
  technologyTerm('openaiOverview', 'base-url', 'Base URL', '基础地址', '相对端点路径解析时所基于的共同 URL 前缀。', 'The common URL prefix against which relative endpoint paths are resolved.');
  technologyTerm('openaiOverview', 'api-key', 'API Key', 'API 密钥', '用于验证 API 请求且必须作为秘密保护的凭据。', 'A credential used to authenticate API requests and kept secret.', ['api_key']);
  technologyTerm('openaiOverview', 'openai-api-key-environment-variable', 'OPENAI_API_KEY', 'OpenAI API 密钥环境变量', 'OpenAI 客户端常用于读取 API 密钥的环境变量名。', 'The environment-variable name commonly used by OpenAI clients to read an API key.');
  technologyTerm('openaiOverview', 'bearer-authentication', 'Bearer Authentication', 'Bearer 身份验证', '在 Authorization 请求头的 Bearer 方案中传递凭据的认证方式。', 'Authentication that carries a credential with the Bearer scheme in the Authorization header.');
  technologyTerm('openaiOverview', 'authorization-header', 'Authorization Header', 'Authorization 请求头', '承载 API 认证方案和凭据的 HTTP 请求头。', 'The HTTP request header carrying an API authentication scheme and credential.');
  technologyTerm('openaiOverview', 'bearer-scheme', 'Bearer', 'Bearer 方案', 'Authorization 请求头中表示持有者令牌认证的方案名称。', 'The Authorization-header scheme name indicating bearer-token authentication.');
  technologyTerm('openaiOverview', 'bearer-token', 'Bearer Token', 'Bearer 令牌', '持有者可直接用于进行请求认证的访问令牌。', 'An access token whose holder can use it directly to authenticate a request.');
  technologyTerm('openaiOverview', 'authorization-bearer', 'Authorization: Bearer', 'Bearer 授权头语法', '在 Authorization 请求头中声明 Bearer 认证方案的语法前缀。', 'The syntax prefix declaring the Bearer authentication scheme in an Authorization header.');
  technologyTerm('openaiChat', 'chat-completions-api', 'Chat Completions API', '聊天补全接口', '根据对话消息创建完整或流式聊天补全响应的 HTTP 接口。', 'The HTTP API that creates complete or streamed chat-completion responses from conversation messages.');
  technologyTerm('openaiChat', 'chat-completions-path', '/v1/chat/completions', '聊天补全端点路径', '创建聊天补全所使用的版本化 HTTP 端点路径。', 'The versioned HTTP endpoint path used to create a chat completion.');
  technologyTerm('openaiChat', 'post-chat-completions-operation', 'POST /v1/chat/completions', '创建聊天补全 HTTP 操作', '使用 POST 方法向聊天补全端点提交请求的 HTTP 操作。', 'The HTTP operation that submits a request to the chat-completions endpoint with the POST method.');
  technologyTerm('openaiChat', 'create-chat-completion-operation', 'Create Chat Completion', '创建聊天补全', '根据一组对话消息创建聊天补全响应的 API 操作。', 'The API operation that creates a chat-completion response from a sequence of conversation messages.');
  technologyTerm('openaiModels', 'models-api', 'Models API', '模型接口', '用于发现可用模型及其基本元数据的 HTTP 接口。', 'The HTTP API used to discover available models and their basic metadata.');
  technologyTerm('openaiModels', 'models-path', '/v1/models', '模型端点路径', '列出模型所使用的版本化 HTTP 端点路径。', 'The versioned HTTP endpoint path used to list models.');
  technologyTerm('openaiModels', 'models-endpoint', 'Models Endpoint', '模型端点', '用于发现可用模型及其基本元数据的 API 端点。', 'The API endpoint used to discover available models and their basic metadata.');
  technologyTerm('openaiModels', 'model-catalog', 'Model Catalog', '模型目录', '模型发现端点返回的可用模型集合。', 'The set of available models returned by a model-discovery endpoint.');
  technologyTerm('openaiModels', 'list-models', 'List Models', '列出模型', '获取可用模型基本信息的 API 操作。', 'The API operation that retrieves basic information about available models.', ['listModels']);
  technologyTerm('openaiModels', 'get-models-operation', 'GET /v1/models', '获取模型列表操作', '通过 GET 方法请求 /v1/models 路径的模型发现操作。', 'The model-discovery operation that requests /v1/models with the GET method.');
  technologyTerm('openaiModels', 'relative-models-path', '/models', '相对模型路径', '相对于版本化 API 基础地址的模型资源路径。', 'The model-resource path relative to a versioned API base URL.');
  technologyTerm('openaiModels', 'model-list-object', 'Model List Object', '模型列表对象', '以 object 为 list 并用 data 数组封装模型的响应对象。', 'A response object wrapping models with object set to list and a data array.');
  technologyTerm('openaiModels', 'model-list-object-value', 'object=list', '模型列表对象类型值', '表示响应对象为列表的 object 字段赋值。', 'The object-field assignment indicating that a response object is a list.');
  technologyTerm('openaiModels', 'data-field', 'data', '数据字段', '模型列表对象中承载模型对象数组的字段。', 'The field carrying the array of model objects in a model-list object.');
  technologyTerm('openaiModels', 'model-id-field-path', 'data[].id', '模型 ID 字段路径', '指向模型列表中每个模型对象标识符的字段路径。', 'The field path to each model object\'s identifier in a model list.');
  technologyTerm('openaiModels', 'model-object-field-path', 'data[].object', '模型对象类型字段路径', '指向模型列表中每个模型对象类型判别值的字段路径。', 'The field path to each model object\'s type discriminator in a model list.');
  technologyTerm('openaiModels', 'model-created-field-path', 'data[].created', '模型创建时间字段路径', '指向模型列表中每个模型对象创建时间的字段路径。', 'The field path to each model object\'s creation timestamp in a model list.');
  technologyTerm('openaiModels', 'model-owner-field-path', 'data[].owned_by', '模型所有者字段路径', '指向模型列表中每个模型对象所有方的字段路径。', 'The field path to each model object\'s owner in a model list.');
  technologyTerm('openaiModels', 'model-object', 'Model Object', '模型对象', '包含模型标识、对象类型、创建时间和所有者的 API 对象。', 'An API object containing a model identifier, object type, creation time, and owner.');
  technologyTerm('openaiModels', 'model-object-value', 'object=model', '模型对象类型值', '表示 API 对象为模型的 object 字段赋值。', 'The object-field assignment indicating that an API object is a model.');
  technologyTerm('openaiModels', 'model-owner', 'Model Owner', '模型所有者', '模型元数据所表示的模型所有方。', 'The owner represented by a model\'s metadata.');
  technologyTerm('openaiModels', 'owned-by-field', 'owned_by', '模型所有者字段', '模型对象中表示模型所有方的字段。', 'The field in a model object identifying the model owner.');
  technologyTerm('openaiChat', 'api-object-type', 'API Object Type', 'API 对象类型', '用于区分 API 对象种类的字符串类别。', 'A string category used to distinguish kinds of API objects.');
  technologyTerm('openaiChat', 'object-field', 'object', '对象类型字段', 'API 对象中承载对象类型判别值的字段。', 'The field carrying an object-type discriminator in an API object.');
  technologyTerm('openaiChat', 'created-timestamp', 'Created Timestamp', '创建时间戳', '以 Unix 秒表示的对象创建时间。', 'Object creation time expressed as Unix seconds.');
  technologyTerm('openaiChat', 'created-field', 'created', '创建时间字段', 'API 对象中以 Unix 秒表示创建时间的字段。', 'The field storing API-object creation time as Unix seconds.');
  technologyTerm('openaiChat', 'chat-completion-object', 'Chat Completion Object', '聊天补全对象', '非流式请求返回的完整聊天补全响应对象。', 'The complete chat-completion response object returned for a non-streaming request.');
  technologyTerm('openaiChat', 'chat-completion-object-value', 'chat.completion', '聊天补全对象类型值', '表示 API 对象为完整聊天补全的 object 字段值。', 'The object-field value indicating a complete chat-completion object.');
  technologyTerm('openaiChat', 'chat-completion-id', 'Chat Completion ID', '聊天补全 ID', '唯一标识一次聊天补全的字符串。', 'The string uniquely identifying a chat completion.');
  technologyTerm('openaiChat', 'chatcmpl-prefix', 'chatcmpl', '聊天补全 ID 前缀', '聊天补全标识符常用的字符串前缀。', 'The string prefix commonly used by chat-completion identifiers.');
  technologyTerm('openaiChat', 'completion-id-field', 'completion_id', '补全 ID 字段', '承载补全对象标识符的字段名。', 'The field name carrying a completion-object identifier.');
  technologyTerm('openaiChat', 'chat-completion-choice', 'Chat Completion Choice', '聊天补全候选项', '聊天补全 choices 数组中的一个生成候选结果。', 'One generated candidate result in a chat completion\'s choices array.');
  technologyTerm('openaiChat', 'choices-field', 'choices', '候选项数组字段', '聊天补全对象中承载生成候选结果数组的字段。', 'The field carrying an array of generated candidates in a chat-completion object.');
  technologyTerm('openaiChat', 'choice-message-field-path', 'choices[].message', '候选消息字段路径', '指向每个候选项中完整生成消息对象的字段路径。', 'The field path to the complete generated message object in each choice.');
  technologyTerm('openaiChat', 'choice-message-role-field-path', 'choices[].message.role', '候选消息角色字段路径', '指向完整候选消息角色字段的字段路径。', 'The field path to the role of a complete choice message.');
  technologyTerm('openaiChat', 'choice-message-content-field-path', 'choices[].message.content', '候选消息内容字段路径', '指向完整候选消息内容字段的字段路径。', 'The field path to the content of a complete choice message.');
  technologyTerm('openaiChat', 'choice-index', 'Choice Index', '候选项序号', '候选结果在 choices 数组内的位置。', 'The position of a candidate result in the choices array.');
  technologyTerm('openaiChat', 'index-field', 'index', '候选项序号字段', '候选结果中记录其数组位置的整数值字段。', 'The integer field recording a candidate result\'s position in an array.');
  technologyTerm('openaiChat', 'choice-index-field-path', 'choices[].index', '候选项序号字段路径', '指向 choices 数组元素序号字段的限定字段路径。', 'The qualified field path referring to an element index in the choices array.');
  technologyTerm('openaiChat', 'finish-reason', 'Finish Reason', '结束原因', '说明生成为何结束的字段。', 'The field explaining why generation ended.', ['finish_reason']);
  technologyTerm('openaiChat', 'choice-finish-reason-field-path', 'choices[].finish_reason', '候选项结束原因字段路径', '指向候选项结束原因字段的字段路径。', 'The field path to a choice\'s finish reason.');
  technologyTerm('openaiChat', 'stop-finish-reason', 'Stop Finish Reason', '停止结束原因', 'finish_reason 为 stop 时表示生成正常结束的结束原因。', 'A finish reason whose stop value indicates that generation ended normally.');
  technologyTerm('openaiChat', 'chat-completion-chunk', 'Chat Completion Chunk', '聊天补全分块', '流式响应逐次发送的聊天补全增量对象。', 'An incremental chat-completion object sent in a streaming response.');
  technologyTerm('openaiChat', 'chat-completion-chunk-value', 'chat.completion.chunk', '聊天补全分块对象类型值', '表示 API 对象为聊天补全流式分块的 object 字段值。', 'The object-field value indicating a streamed chat-completion chunk.');
  technologyTerm('openaiChat', 'message-delta', 'Delta', '增量字段', '流式聊天补全分块中携带部分消息更新的字段。', 'The field carrying a partial message update in a streamed chat-completion chunk.');
  technologyTerm('openaiChat', 'choice-delta-field-path', 'choices[].delta', '候选项增量字段路径', '指向流式候选项增量对象的限定字段路径。', 'The qualified field path referring to a streamed choice delta object.');
  technologyTerm('openaiChatStreaming', 'delta-role-field-path', 'choices[].delta.role', '增量角色字段路径', '指向流式消息增量中角色字段的字段路径。', 'The field path to the role in a streamed message delta.');
  technologyTerm('openaiChatStreaming', 'delta-content-field-path', 'choices[].delta.content', '增量内容字段路径', '指向流式消息增量中内容字段的字段路径。', 'The field path to content in a streamed message delta.');
  technologyTerm('openaiChat', 'server-sent-events', 'Server-Sent Events', '服务器发送事件', '服务器通过单个 HTTP 响应持续推送事件的流式格式。', 'A streaming format in which a server continuously pushes events through one HTTP response.', ['SSE', 'server sent events']);
  technologyTerm('openaiChat', 'event-stream-media-type', 'text/event-stream', '事件流媒体类型', '服务器发送事件响应使用的 HTTP 媒体类型。', 'The HTTP media type used for a server-sent-events response.');
  technologyTerm('openaiChat', 'assistant-role-assignment', 'role: assistant', '助手角色赋值', 'role 字段取 assistant 值时表示消息由助手角色生成。', 'The assignment of assistant to the role field, indicating a message generated by the assistant role.');
  technologyTerm('openaiChat', 'non-streaming-response', 'Non-Streaming Response', '非流式响应', '一次返回的完整 JSON 响应。', 'A complete JSON response returned at once.');
  technologyTerm('openaiChat', 'stream-false', 'stream=false', '关闭流式响应', '把 stream 布尔参数设为 false 的赋值。', 'The assignment setting the stream boolean parameter to false.');
  technologyTerm('openaiOpenApi', 'openai-error-object', 'OpenAI Error Object', 'OpenAI 错误对象', '顶层 error 字段中承载消息、类型、参数和代码的结构化错误。', 'A structured error under the top-level error field carrying a message, type, parameter, and code.');
  technologyTerm('openaiOpenApi', 'error-field', 'error', '错误对象字段', 'API 错误响应中承载结构化错误对象的顶层字段。', 'The top-level field carrying a structured error object in an API error response.');
  technologyTerm('openaiOpenApi', 'error-message', 'Error Message', '错误消息', '供人阅读的失败说明。', 'The human-readable explanation of a failure.');
  technologyTerm('openaiOpenApi', 'error-message-field-path', 'error.message', '错误消息字段路径', '指向错误对象中人类可读消息字段的限定字段路径。', 'The qualified field path referring to the human-readable message in an error object.');
  technologyTerm('openaiOpenApi', 'error-type', 'Error Type', '错误类型', '表示错误类别的机器可读值。', 'A machine-readable value identifying an error category.');
  technologyTerm('openaiOpenApi', 'error-type-field-path', 'error.type', '错误类型字段路径', '指向错误对象中机器可读类型字段的限定字段路径。', 'The qualified field path referring to the machine-readable type in an error object.');
  technologyTerm('openaiOpenApi', 'error-parameter', 'Error Parameter', '错误参数', '与失败有关的请求参数名，无特定参数时可为空。', 'The request parameter associated with a failure, or null when none applies.');
  technologyTerm('openaiOpenApi', 'error-param-field-path', 'error.param', '错误参数字段路径', '指向错误对象中相关请求参数字段的限定字段路径。', 'The qualified field path referring to the associated request parameter in an error object.');
  technologyTerm('openaiOpenApi', 'param-field', 'param', '错误参数字段', '错误对象中标识相关请求参数的字段。', 'The field in an error object identifying the associated request parameter.');
  technologyTerm('openaiOpenApi', 'error-code', 'Error Code', '错误代码', '供程序分支处理的机器可读失败标识。', 'A machine-readable failure identifier used for programmatic handling.', ['error_code']);
  technologyTerm('openaiOpenApi', 'error-code-field-path', 'error.code', '错误代码字段路径', '指向错误对象中机器可读代码字段的限定字段路径。', 'The qualified field path referring to the machine-readable code in an error object.');
  technologyTerm('openaiErrors', 'bad-request-error', 'Bad Request Error', '错误请求', '表示请求格式错误、缺少必需参数或包含无效输入的错误类别。', 'An error category indicating a malformed request, missing required parameters, or invalid input.', ['BadRequestError']);
  technologyTerm('openaiErrors', 'invalid-request-error-value', 'invalid_request_error', '无效请求错误类型值', '表示请求缺少必需参数或包含无效输入的机器可读错误类型值。', 'A machine-readable error-type value indicating missing required parameters or invalid input.');
  technologyTerm('openaiErrors', 'internal-server-error', 'Internal Server Error', '内部服务器错误', '表示服务端处理请求时发生内部故障的错误类别。', 'An error category indicating an internal failure while the server was processing a request.', ['InternalServerError']);
  technologyTerm('openaiErrors', 'server-error-value', 'server_error', '服务器错误类型值', '表示服务端内部故障的机器可读错误类型值。', 'A machine-readable error-type value indicating an internal server failure.');
  technologyTerm('openaiErrors', 'http-500', 'HTTP 500', 'HTTP 500 状态', '表示服务器内部错误的 HTTP 响应状态码。', 'The HTTP response status code indicating an internal server error.');
  technologyTerm('openaiOverview', 'request-id', 'Request ID', '请求标识符', '用于关联、记录和排查单次 API 请求的唯一标识。', 'A unique identifier used to correlate, log, and troubleshoot one API request.', ['request_id']);
  technologyTerm('openaiOverview', 'x-request-id-header', 'X-Request-ID', '请求 ID 头', '在 HTTP 请求头或响应头中传递请求标识符的字段名。', 'The HTTP request- or response-header field name carrying a request identifier.');
  technologyTerm('openaiChat', 'json-request-body', 'JSON Request Body', 'JSON 请求体', '以 UTF-8 JSON 对象编码并提交给 API 的请求正文。', 'An API request body encoded as a UTF-8 JSON object.');
  technologyTerm('openaiChat', 'json-media-type', 'application/json', 'JSON 媒体类型', '表示正文使用 JSON 编码的 HTTP 媒体类型。', 'The HTTP media type indicating that a body is encoded as JSON.');
  technologyTerm('openaiChat', 'api-response-body', 'API Response Body', 'API 响应正文', 'API 通过 JSON 或事件流返回给客户端的序列化正文。', 'The serialized JSON or event-stream body returned by an API to a client.');
  technologyTerm('openaiChat', 'response-body-field', 'response_body', '响应正文字段', '记录 API 响应序列化正文的字段。', 'A field recording the serialized body of an API response.');
  technologyTerm('openaiChat', 'content-type', 'Content Type', '内容类型', '表明正文使用 JSON 或事件流等媒体格式的元数据。', 'Metadata identifying the media format of a body, such as JSON or an event stream.', ['Content-Type', 'content_type']);
  technologyTerm('openaiChat', 'response-content-type-field', 'response_content_type', '响应内容类型字段', '记录 API 响应正文媒体类型的字段。', 'A field recording the media type of an API response body.');
  technologyTerm('openaiErrors', 'http-status-code', 'HTTP Status Code', 'HTTP 状态码', '表示 API 请求成功或失败类别的三位数字响应状态。', 'A three-digit response status identifying the success or failure class of an API request.');
  technologyTerm('openaiErrors', 'http-status-field', 'http_status', 'HTTP 状态字段', '记录 API 响应 HTTP 状态码的字段。', 'A field recording the HTTP status code of an API response.');

  technologyTerm('deepBackends', 'file-system', 'File System', '文件系统', '用于组织、读取和写入文件及目录的存储界面。', 'A storage interface for organizing, reading, and writing files and directories.');
  technologyTerm('agentShellSystemManagement', 'data-root', 'Data Root', '数据根', '集中保存一个 Agent Shell 实例配置、状态、用户文件、用户资源和日志的顶层持久目录。', 'The top-level persistent directory containing one Agent Shell instance\'s settings, state, user files, user resources, and logs.');
  technologyTerm('agentShellSystemManagement', 'file-management-scope', 'File Management Scope', '文件管理作用域', '文件管理页面可访问的一个固定用户数据分区；所有操作都限制在当前作用域内。', 'A fixed user-data partition exposed by the file manager; every operation stays inside the current scope.', ['file scope']);
  technologyTerm('deepSkills', 'skills-middleware', 'Skills Middleware', '技能中间件', '向智能体展示可用技能并支持按需读取技能内容的中间件。', 'Middleware that exposes available skills to an agent and supports loading skill content on demand.', ['SkillsMiddleware']);
  technologyTerm('deepSubagents', 'subagent-middleware', 'Subagent Middleware', '子智能体中间件', '通过任务工具向主智能体提供子智能体委派能力的中间件。', 'Middleware that provides a main agent with subagent delegation through a task tool.', ['SubAgentMiddleware']);


entries.sort((left, right) => {
  if (left.english < right.english) return -1
  if (left.english > right.english) return 1
  return 0
})

export const glossaryEntries: readonly GlossaryEntry[] = entries
