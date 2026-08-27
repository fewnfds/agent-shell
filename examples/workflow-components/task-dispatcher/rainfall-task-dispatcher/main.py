"""Dispatch rainfall readings to routine-report or alert Agents.

Expected Workflow State example::

    state["shared_vars"]["rainfall_readings"] = [
        {"station_id": "north-gauge", "millimeters": 18.5},
        {"station_id": "river-gauge", "millimeters": 72.0},
    ]

Create Dispatch Edges named ``rainfall-report`` and ``rainfall-alert``. Each
reading becomes one private worker task. Readings at or above 50 mm use the
alert edge; the others use the report edge. The parent Workflow State receives
the total and alert counts after dispatch.

The field names, threshold, and edge keys are editable example policy. The
stable adapter contract is ``create_dispatcher()`` returning an async
``dispatch(state, runtime)`` that emits JSON payloads. This package uses only
the Python standard library.
"""

from math import isfinite
from typing import Any


ALERT_THRESHOLD_MM = 50.0
REPORT_EDGE = "rainfall-report"
ALERT_EDGE = "rainfall-alert"


def _task_for(reading: dict[str, Any]) -> dict[str, Any]:
    """Validate one reading and turn it into a stable dispatch task."""

    station_id = reading.get("station_id")
    if not isinstance(station_id, str) or not station_id.strip():
        raise ValueError("each rainfall reading requires a non-empty station_id")
    station_id = station_id.strip()

    millimeters = reading.get("millimeters")
    if (
        not isinstance(millimeters, (int, float))
        or isinstance(millimeters, bool)
        or not isfinite(float(millimeters))
        or millimeters < 0
    ):
        raise ValueError("rainfall millimeters must be a finite non-negative number")

    is_alert = millimeters >= ALERT_THRESHOLD_MM
    return {
        # Stable business identity lets downstream aggregation match results.
        "task_id": f"rainfall:{station_id}",
        "dispatch_key": ALERT_EDGE if is_alert else REPORT_EDGE,
        # Worker-specific input belongs in payload, not parent State updates.
        "payload": {
            "station_id": station_id,
            "millimeters": millimeters,
            "alert_threshold_mm": ALERT_THRESHOLD_MM,
            "is_alert": is_alert,
        },
    }


def create_dispatcher():
    """Create the async callable required by the task-dispatcher adapter."""

    async def dispatch(state, runtime):
        # A dispatcher may also read runtime.context or runtime.store. This
        # example needs only Workflow State, so `runtime` remains available for
        # the user to extend without changing the required callable signature.
        shared_vars = state.get("shared_vars", {})
        readings = (
            shared_vars.get("rainfall_readings")
            if isinstance(shared_vars, dict)
            else None
        )
        if not isinstance(readings, list) or not readings:
            raise ValueError("shared_vars.rainfall_readings must be a non-empty list")
        if not all(isinstance(reading, dict) for reading in readings):
            raise ValueError("each rainfall reading must be an object")

        tasks = [_task_for(reading) for reading in readings]
        alert_count = sum(task["payload"]["is_alert"] for task in tasks)
        return {
            "tasks": tasks,
            "update": {
                "shared_vars": {
                    "rainfall_dispatched_count": len(tasks),
                    "rainfall_alert_count": alert_count,
                }
            },
        }

    return dispatch
