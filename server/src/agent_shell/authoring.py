from __future__ import annotations

from copy import deepcopy

from agent_shell.capability_manifest import CAPABILITY_BY_TYPE
from agent_shell.contracts import (
    CheckpointerBlock,
    DEFAULT_EXCEPTION_RETRY_CONDITIONS,
    EXCEPTION_RETRY_CONDITIONS,
    EXCEPTION_RETRY_STRATEGIES,
    ExceptionRetryBlock,
    FilesystemBlock,
    FilesystemToolConfigs,
    PromptCachingBlock,
    SKILL_PROMPT_FIELDS,
    SummarizationBlock,
)


# These text snapshots are management-editor data. Production catalog reads must not
# import optional runtime packages merely to render a form. A focused authoring test
# compares them with the locked LangChain/DeepAgents defaults so dependency upgrades
# cannot silently make the editor stale.
FILESYSTEM_EDITOR_SYSTEM_PROMPT = ""

DEEPAGENTS_SUMMARY_PROMPT = """<role>
Context Extraction Assistant
</role>

<primary_objective>
Your sole objective in this task is to extract the highest quality/most relevant context from the conversation history below.
</primary_objective>

<objective_information>
You're nearing the total number of input tokens you can accept, so you must extract the highest quality/most relevant pieces of information from your conversation history.
This context will then overwrite the conversation history presented below. Because of this, ensure the context you extract is only the most important information to continue working toward your overall goal.
</objective_information>

<instructions>
The conversation history below will be replaced with the context you extract in this step.
You want to ensure that you don't repeat any actions you've already completed, so the context you extract from the conversation history should be focused on the most important information to your overall goal.

You should structure your summary using the following sections. Each section acts as a checklist - you must populate it with relevant information or explicitly state "None" if there is nothing to report for that section:

## SESSION INTENT

What is the user's primary goal or request? What overall task are you trying to accomplish? This should be concise but complete enough to understand the purpose of the entire session.

## SUMMARY

Extract and record all of the most important context from the conversation history. Include important choices, conclusions, or strategies determined during this conversation. Include the reasoning behind key decisions. Document any rejected options and why they were not pursued.

## ARTIFACTS

What artifacts, files, or resources were created, modified, or accessed during this conversation? For file modifications, list specific file paths and briefly describe the changes made to each. This section prevents silent loss of artifact information.

## NEXT STEPS

What specific tasks remain to be completed to achieve the session intent? What should you do next?

</instructions>

The user will message you with the full message history from which you'll extract context to create a replacement. Carefully read through it all and think deeply about what information is most important to your overall goal and should be saved:

With all of this in mind, please carefully read over the entire conversation history, and extract the most important and relevant context to replace it so that you can free up space in the conversation history.
Respond ONLY with the extracted context. Do not include any additional information, or text before or after the extracted context.

<media_reference_information>
Conversation history may include XML media reference tags, for example:
<image url="/conversation_history/media/{{hash}}.png" />
These tags mean the original message included media that was preserved at the referenced backend path.
Treat the tag and path as part of the conversation context. Do not infer visual details that are not available from surrounding text.
When the media could be important for future context, preserve the media reference in your summary.
The model consuming the summary can call `read_file` on the referenced path if it needs to inspect the media.
</media_reference_information>

<messages>
Messages to summarize:
{messages}
</messages>"""

LIST_FILES_TOOL_DESCRIPTION = """Lists all files in a directory.

This is useful for exploring the filesystem and finding the right file to read or edit.
You should almost ALWAYS use this tool before using the read_file or edit_file tools."""

READ_FILE_TOOL_DESCRIPTION = """Reads a file from the filesystem. Assume any path the user provides is valid; reading a missing file returns an error.

Usage:
- By default, it reads up to 100 lines starting from the beginning of the file. Use `offset`/`limit` to page through large files instead of reading them whole.
- Results are returned with line numbers starting at `offset` + 1 (1 by default), then two spaces, then the source line. Never include these line-number prefixes when editing.
- Lines over 5,000 characters are split with continuation markers (e.g. 5.1, 5.2); `limit` counts source lines, so continuation rows do not consume the budget.
- Speculatively batch multiple `read_file` calls in one response when several files may be useful.
- An empty file returns a system-reminder warning in place of contents.
- Large tool results may be offloaded to a file; the tool message gives the path. Read that path here, paging with `offset`/`limit`.
- Images (`.png`, `.jpg`, etc.), audio, video, and PDFs return multimodal content blocks (https://docs.langchain.com/oss/python/langchain/messages#multimodal).
- For images and PDFs, pagination via `offset`/`limit` is text-only - supply `file_path` only
- Always read a file before editing it."""

WRITE_FILE_TOOL_DESCRIPTION = """Writes content to a file. Creates the file if it does not exist; replaces it entirely if it does.

Usage:
- Use this tool when you intend to create a new file or replace the whole file. You do not need to read the file first.
- Prefer to edit existing files (with the edit_file tool) over creating new ones when possible.
"""

EDIT_FILE_TOOL_DESCRIPTION = """Performs exact string replacements in files.

Usage:
- You must read the file before editing; this tool errors otherwise.
- Preserve the exact indentation from the read output, and never include line-number prefixes in old_string or new_string.
- Prefer editing an existing file over creating a new one.
- Only use emojis if the user explicitly requests it."""

DELETE_TOOL_DESCRIPTION = """Deletes a file or directory from the filesystem.

Usage:
- Permanently removes the file or directory at the given absolute path.
- Deleting a directory removes it and everything inside it, recursively. Prefer
  deleting a directory in one call over deleting each file individually.
- This cannot be undone, so only delete paths you are sure are no longer needed.
"""

GLOB_TOOL_DESCRIPTION = """Find files matching a glob pattern, returning absolute paths.

Supports `*` (any characters within a path segment), `**` (any directories), `?` (single character), `[abc]` (one character from a set), and `{a,b}` (alternatives), e.g. `*.py`, `src/**/*.py`, `*.{yml,yaml}`.

A pattern without `/` matches the file name at any depth under the search root (`*.py` matches `src/app/main.py`). A pattern containing `/` matches the search-root-relative path (`src/**/*.py`). A leading `/` anchors to the search root (`/*.py` matches only top-level Python files).

Leading-dot names are only matched when the pattern segment itself starts with `.` (use `.env`, or `.github/**/*.yml`). Because `**` will not descend into dot-directories, the bare form `*.yml` is *broader* than `**/*.yml` and is usually what you want."""

GREP_TOOL_DESCRIPTION = """Search for a LITERAL text pattern across files (NOT regex).

The pattern is matched verbatim: regex metacharacters are ordinary characters, not operators. To match any of several strings, run a separate grep for each; `grep(pattern="foo|bar")` searches for the literal text "foo|bar", and `.*` or `\\.` match those characters literally.
- If you genuinely need regex, use the execute tool with `rg '<regex>'` instead.

Returns matching files or content per `output_mode`. Offloaded large tool results live under the artifacts root (`/large_tool_results/` by default); grep that directory to search them when you do not know the exact path."""

EXECUTE_TOOL_DESCRIPTION = """Executes a shell command in an isolated sandbox and returns combined stdout/stderr with the exit code (truncated if very large).

Usage:
- Quote paths containing spaces (e.g. cd "/path/with spaces").
- Chain commands with ';' or '&&' (use '&&' when a command depends on the previous); do not use newlines except inside quoted strings.
- Use absolute paths and avoid `cd` so the working directory stays stable; use the optional timeout to override the default (0 disables it on backends that support that).
- You MUST avoid using search commands like find and grep. Instead use the grep, glob tools to search. Use read_file rather than cat/head/tail.
    - execute(command="find . -name '*.py'")  # Use glob tool instead
    - execute(command="grep -r 'pattern' .")  # Use grep tool instead

Only available on backends implementing SandboxBackendProtocol; otherwise it returns an error.

Additional Agent Shell runtime notes:
- The standard Windows launcher provides `python` from its bundled runtime.
- `npm`, `make`, `pytest`, and other external programs are available only when the selected backend or user workspace explicitly provides them; do not assume they are installed.
"""

SKILLS_SYSTEM_PROMPT = """## Skills System

You have access to a skills library that provides specialized capabilities and domain knowledge.

{skills_locations}{skills_load_warnings}

Sources labeled "Deepagents" are specific to this agent tool; sources labeled "Agents" are shared across all agent tools on this machine.

**Available Skills:**

{skills_list}

**How to Use Skills (Progressive Disclosure):**

Skills follow a **progressive disclosure** pattern - you see their name and description above, but only read full instructions when needed:

1. **Recognize when a skill applies**: Check if the user's task matches a skill's description
2. **Read the skill's full instructions**: Use `read_file` on the path shown in the skill list above.
    Pass `limit=1000` since the default of 100 lines is too small for most skill files.
3. **Follow the skill's instructions**: SKILL.md contains step-by-step workflows, best practices, and examples
4. **Access supporting files**: Skills may include helper scripts, configs, or reference docs - use absolute paths

**When to Use Skills:**

- User's request matches a skill's domain (e.g., "research X" -> web-research skill)
- You need specialized knowledge or structured workflows
- A skill provides proven patterns for complex tasks

**Executing Skill Scripts:**
Skills may contain Python scripts or other executable files. Always use absolute paths from the skill list.

**Example Workflow:**

User: "Can you research the latest developments in quantum computing?"

1. Check available skills -> See "web-research" skill with its path
2. Read the full skill file: `read_file(file_path="...", limit=1000)`
3. Follow the skill's research workflow (search -> organize -> synthesize)
4. Use any helper scripts with absolute paths

Remember: Skills make you more capable and consistent. When in doubt, check if a skill exists for the task!"""

SUBAGENT_EDITOR_SYSTEM_PROMPT = ""

TASK_TOOL_DESCRIPTION = """Launch an ephemeral subagent to handle a complex, multi-step task in an isolated context window.

Available agent types and the tools they have access to:
{available_agents}

Specify subagent_type to select the agent. Usage notes:
- Launch multiple agents concurrently when their tasks are independent, using a single message with multiple tool calls.
- Each invocation is stateless: the agent sees only the prompt you give it and returns a single final report. Put full detail in the prompt and state exactly what it should return.
- The agent's report is not shown to the user; relay a summary yourself.
- Tell the agent whether to create content, analyze, or only research, since it cannot see the user's intent.
- If an agent's description says to use it proactively, do so without waiting to be asked.
- When only general-purpose is available, use it for any complex, context-heavy task; it has the same capabilities as the main agent."""

WRITE_TODOS_SYSTEM_PROMPT = """## `write_todos`

You have access to the `write_todos` tool to help you manage and plan complex objectives.
Use this tool for complex objectives to ensure that you are tracking each necessary step.
This tool is very helpful for planning complex objectives, and for breaking down these larger complex objectives into smaller steps.

It is critical that you mark todos as completed as soon as you are done with a step. Do not batch up multiple steps before marking them as completed.
For simple objectives that only require a few steps, it is better to just complete the objective directly and NOT use this tool.
Writing todos takes time and tokens, use it when it is helpful for managing complex many-step problems! But not for simple few-step requests.

## Important To-Do List Usage Notes to Remember

- The `write_todos` tool should never be called multiple times in parallel.
- Don't be afraid to revise the To-Do list as you go. New information may reveal new tasks that need to be done, or old tasks that are irrelevant.

## Finishing a task

When you finish all work, write your final answer in the message AFTER your last `write_todos` call — not in the same turn as that call. Start the final message with the substantive content the user asked for — the data, computation, summary, or analysis. The user wants the result, not confirmation that the work is done."""

WRITE_TODOS_TOOL_DESCRIPTION = """Use this tool to create and manage a structured task list for your current work session. This helps you track progress and organize complex tasks.

Only use this tool if you think it will be helpful in staying organized. If the user's request is trivial and takes less than 3 steps, it is better to NOT use this tool and just do the task directly.

## When to Use This Tool

Use this tool in these scenarios:

1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
5. The plan may need future revisions or updates based on results from the first few steps

## How to Use This Tool

1. When you start working on a task - Mark it as in_progress BEFORE beginning work.
2. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation.
3. You can also update future tasks, such as deleting them if they are no longer necessary, or adding new tasks that are necessary. Don't change previously completed tasks.
4. You can make several updates to the todo list at once. For example, when you complete a task, you can mark the next task you need to start as in_progress.

## When NOT to Use This Tool

It is important to skip using this tool when:
1. There is only a single, straightforward task
2. The task is trivial and tracking it provides no benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

## Task States and Management

1. **Task States**: Use these states to track progress:
    - pending: Task not yet started
    - in_progress: Currently working on (you can have multiple tasks in_progress at a time if they are not related to each other and can be run in parallel)
    - completed: Task finished successfully

2. **Task Management**:
    - Update task status in real-time as you work
    - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
    - Complete current tasks before starting new ones
    - Remove tasks that are no longer relevant from the list entirely
    - IMPORTANT: When you write this todo list, you should mark your first task (or tasks) as in_progress immediately!.
    - IMPORTANT: Unless all tasks are completed, you should always have at least one task in_progress.

3. **Task Completion Requirements**:
    - ONLY mark a task as completed when you have FULLY accomplished it
    - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
    - When blocked, create a new task describing what needs to be resolved
    - Never mark a task as completed if:
        - There are unresolved issues or errors
        - Work is partial or incomplete
        - You encountered blockers that prevent completion
        - You couldn't find necessary resources or dependencies
        - Quality standards haven't been met

4. **Task Breakdown**:
    - Create specific, actionable items
    - Break complex tasks into smaller, manageable steps
    - Use clear, descriptive task names

Being proactive with task management ensures you complete all requirements successfully
Remember: If you only need to make a few tool calls to complete a task, and it is clear what you need to do, it is better to just do the task directly and NOT call this tool at all.

## When You Finish

`write_todos` tracks your work; it does not deliver the answer. Whatever the user asked for — computations, summaries, comparisons, data — must appear as text content in a message after your final `write_todos` call. Marking the last todo complete is not itself an answer to the user."""


_FILESYSTEM_TOOL_DESCRIPTIONS = {
    "ls": ("读取", LIST_FILES_TOOL_DESCRIPTION),
    "read_file": ("读取", READ_FILE_TOOL_DESCRIPTION),
    "write_file": ("写入", WRITE_FILE_TOOL_DESCRIPTION),
    "edit_file": ("写入", EDIT_FILE_TOOL_DESCRIPTION),
    "delete": ("删除", DELETE_TOOL_DESCRIPTION),
    "glob": ("检索", GLOB_TOOL_DESCRIPTION),
    "grep": ("检索", GREP_TOOL_DESCRIPTION),
    "execute": ("执行", EXECUTE_TOOL_DESCRIPTION),
}

def _filesystem_tools() -> list[dict[str, object]]:
    defaults = FilesystemToolConfigs().model_dump(mode="json")
    return [
        {
            "name": name,
            "kind": _FILESYSTEM_TOOL_DESCRIPTIONS[name][0],
            "configurable": name not in {"read_file", "execute"},
            "visible": defaults[name]["visible"],
            "default_description": _FILESYSTEM_TOOL_DESCRIPTIONS[name][1],
        }
        for name in CAPABILITY_BY_TYPE["filesystem"].tool_names
    ]


_EDITOR_DEFAULTS = {
    "checkpointer": CheckpointerBlock(name="Checkpointer").model_dump(
        mode="json",
        exclude={"name"},
    ),
    "filesystem": {
        "system_prompt": FILESYSTEM_EDITOR_SYSTEM_PROMPT,
        "tool_token_limit_before_evict": FilesystemBlock.model_fields[
            "tool_token_limit_before_evict"
        ].default,
        "human_message_token_limit_before_evict": FilesystemBlock.model_fields[
            "human_message_token_limit_before_evict"
        ].default,
        "grep_max_count": FilesystemBlock.model_fields["grep_max_count"].default,
        "max_execute_timeout": FilesystemBlock.model_fields[
            "max_execute_timeout"
        ].default,
        "tools": _filesystem_tools(),
    },
    "filesystem_permissions": {
        "system_prompt": FILESYSTEM_EDITOR_SYSTEM_PROMPT,
        "tools": _filesystem_tools(),
    },
    "skill": {
        "system_prompt": SKILLS_SYSTEM_PROMPT,
        "required_placeholders": [f"{{{field}}}" for field in SKILL_PROMPT_FIELDS],
    },
    "subagent": {
        "system_prompt": SUBAGENT_EDITOR_SYSTEM_PROMPT,
        "tool_description": TASK_TOOL_DESCRIPTION,
    },
    "todo_list": {
        "system_prompt": WRITE_TODOS_SYSTEM_PROMPT,
        "tool_description": WRITE_TODOS_TOOL_DESCRIPTION,
    },
    "agent_event_output": {},
    "exception_retry": {
        "strategies": list(EXCEPTION_RETRY_STRATEGIES),
        "conditions": list(EXCEPTION_RETRY_CONDITIONS),
        "default_value": {
            "strategy": ExceptionRetryBlock.model_fields["strategy"].default,
            "force_non_streaming": ExceptionRetryBlock.model_fields[
                "force_non_streaming"
            ].default,
            "max_retries": ExceptionRetryBlock.model_fields["max_retries"].default,
            "retry_on": list(DEFAULT_EXCEPTION_RETRY_CONDITIONS),
        },
    },
    "summarization": {
        **SummarizationBlock(name="Summarization").model_dump(
            mode="json",
            exclude={"name"},
        ),
        "summary_prompt_default": DEEPAGENTS_SUMMARY_PROMPT,
    },
    "prompt_caching": PromptCachingBlock(name="Prompt caching").model_dump(
        mode="json",
        exclude={"name"},
    ),
    "workflow_event_output": {},
    "command": {},
    "task_dispatcher": {},
}


def editor_defaults() -> dict[str, object]:
    """Return the current management form data without importing runtime packages."""

    return deepcopy(_EDITOR_DEFAULTS)
