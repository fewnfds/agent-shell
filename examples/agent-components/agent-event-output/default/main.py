def _details(summary, message):
    return f'<details type="agent"><summary>*{summary}*</summary>{message}</details>\n'


# Fields available to every branch:
# event_type, phase, sequence, timestamp, namespace, agent_name, node,
# source_type, workflow_node_id, agent_profile_id, subagent_profile_id,
# message, data.
# Branch-specific fields:
# assistant_text/reasoning -> message_id
# tool_call -> tool_name, tool_call_id, arguments
# tool_result -> tool_name, tool_call_id, status, output
# tool_error -> tool_name, tool_call_id, status, error_code
# subagent -> subagent_name, tool_call_id, status
# custom -> channel, data_json
# lifecycle -> status, finish_reason, error_code
# data is the complete Python payload. Use message/output/arguments/data_json for
# bounded, normalized text and check event_type before reading optional fields.
#
# This example renders every supported Agent event as an HTML
# <details type="agent"> block. Edit the branches to format or filter events;
# returning an empty string filters an event. The complete event contract is
# documented in docs/wizard-pages/agent-event-output-config.md.
# Return an empty string from a branch to filter that event.
def output(event):
    event_type = event["event_type"]
    agent_name = event["agent_name"]
    message = event["message"]
    if event_type == "assistant_text":
        return _details(f"{agent_name} response", message)
    if event_type == "reasoning":
        return _details(f"{agent_name} reasoning", message)
    if event_type == "tool_call":
        return _details(f'{agent_name} Tool {event["tool_name"]} call', message)
    if event_type == "tool_result":
        return _details(f'{agent_name} Tool {event["tool_name"]} result', message)
    if event_type == "tool_error":
        return _details(f'{agent_name} Tool {event["tool_name"]} error', message)
    if event_type == "subagent":
        return _details(
            f'Subagent {event["subagent_name"]} {event["status"]}',
            message,
        )
    if event_type == "custom":
        return _details(f'{agent_name} Custom {event["channel"]}', message)
    if event_type == "lifecycle":
        return _details(f'{agent_name} Lifecycle {event["status"]}', message)
    return ""
