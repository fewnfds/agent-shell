# Fields available to every branch:
# event_type, phase, sequence, timestamp, namespace, agent_name, node,
# source_type, workflow_node_id, agent_profile_id, subagent_profile_id,
# message, data.
# custom -> channel, data_json
# lifecycle -> status, finish_reason, error_code
# values / updates / tasks / checkpoints / input / input.requested / debug / other -> channel, data_json
# data is the complete Python payload. Use message/data_json for bounded display;
# inspect data only after checking event_type because its shape depends on the method.
#
# This example renders every supported Workflow-owned event as an HTML
# <details type="workflow"> block. Supported event types are custom, lifecycle,
# values, updates, tasks, checkpoints, input, input.requested, debug, and other.
# Edit the branches to format or filter events; returning an empty string filters
# an event. The complete event contract is documented in
# docs/wizard-pages/workflow-event-output-config.md.
# Return an empty string from a branch to filter that event.

def _details(summary, message):
    return f'<details type="workflow"><summary>*{summary}*</summary>{message}</details>\n'

def output(event):
    event_type = event["event_type"]
    if event_type == "custom":
        return _details(f'Workflow Custom {event["channel"]}', event["message"])
    if event_type == "lifecycle":
        return _details(f'Workflow Lifecycle {event["status"]}', event["message"])
    if event_type == "values":
        return _details("Workflow Values", event["message"])
    if event_type == "updates":
        return _details(f'Workflow Updates {event["channel"]}', event["message"])
    if event_type == "tasks":
        return _details(f'Workflow Tasks {event["channel"]}', event["message"])
    if event_type == "checkpoints":
        return _details(
            f'Workflow Checkpoints {event["channel"]}', event["message"]
        )
    if event_type == "input":
        return _details(f'Workflow Input {event["channel"]}', event["message"])
    if event_type == "input.requested":
        return _details(
            f'Workflow Input Requested {event["channel"]}', event["message"]
        )
    if event_type == "debug":
        return _details(f'Workflow Debug {event["channel"]}', event["message"])
    if event_type == "other":
        return _details(f'Workflow Other {event["channel"]}', event["message"])
    return ""
