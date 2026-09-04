"""Dispatch rainfall readings to report or alert Agent Nodes.

Create Dispatch Edges named ``rainfall-report`` and ``rainfall-alert``. Each
reading becomes one private Agent task. Readings at or above 50 mm use the
alert Edge; other readings use the report Edge. The Workflow State
receives total and alert counts through ``update``.

The field names, threshold, and Edge keys are editable example policy. The
package uses the Command ``create_command()`` factory contract and only the
Python standard library.
"""

from math import isfinite
from typing import Any


ALERT_THRESHOLD_MM = 50.0
REPORT_EDGE = "rainfall-report"
ALERT_EDGE = "rainfall-alert"


def _task_for(reading: dict[str, Any]) -> dict[str, Any]:
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
        "task_id": f"rainfall:{station_id}",
        "dispatch_key": ALERT_EDGE if is_alert else REPORT_EDGE,
        "payload": {
            "station_id": station_id,
            "millimeters": millimeters,
            "alert_threshold_mm": ALERT_THRESHOLD_MM,
            "is_alert": is_alert,
        },
    }


def create_command():
    async def command(state, runtime):
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
            "dispatch": tasks,
            "update": {
                "shared_vars": {
                    "rainfall_dispatched_count": len(tasks),
                    "rainfall_alert_count": alert_count,
                }
            },
        }

    return command
