"""Select a report or alert Command Node from rainfall control data."""

from math import isfinite

from langgraph.types import Command


ALERT_THRESHOLD_MM = 50.0


def create_command():
    async def command(state, runtime):
        del runtime
        shared_vars = state.get("shared_vars", {})
        readings = (
            shared_vars.get("rainfall_readings")
            if isinstance(shared_vars, dict)
            else None
        )
        if not isinstance(readings, list) or not readings:
            raise ValueError("shared_vars.rainfall_readings must be a non-empty list")
        millimeters = [reading.get("millimeters") for reading in readings]
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not isfinite(float(value))
            or value < 0
            for value in millimeters
        ):
            raise ValueError("rainfall millimeters must be finite non-negative numbers")
        alert_count = sum(value >= ALERT_THRESHOLD_MM for value in millimeters)
        return Command(
            update={
                "shared_vars": {
                    "rainfall_reading_count": len(readings),
                    "rainfall_alert_count": alert_count,
                }
            },
            goto="alert" if alert_count else "report",
        )

    return command
