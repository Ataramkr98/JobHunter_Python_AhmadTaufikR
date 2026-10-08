"""Human-readable rendering of the stored cron expression.

Sources store their ingestion cadence as a standard 5-field cron string. Printing
that string raw is both ugly and, once HTML-escaped, actively misleading — the
asterisks in ``0 */6 * * *`` come out as ``*&#47;6 ***`` on the page. Operators
reading the source-health dashboard need "every 6 hours", not a cron.
"""
from __future__ import annotations

_HOUR_NAMES = {
    0: "midnight", 1: "1am", 2: "2am", 3: "3am", 4: "4am", 5: "5am", 6: "6am",
    7: "7am", 8: "8am", 9: "9am", 10: "10am", 11: "11am", 12: "noon",
    13: "1pm", 14: "2pm", 15: "3pm", 16: "4pm", 17: "5pm", 18: "6pm",
    19: "7pm", 20: "8pm", 21: "9pm", 22: "10pm", 23: "11pm",
}


def _step_of(field: str) -> int | None:
    """Return N for a ``*/N`` field, or None if it is not a step expression."""
    if not field.startswith("*/"):
        return None
    try:
        step = int(field[2:])
    except ValueError:
        return None
    return step if step > 0 else None


def describe_cron(expression: str | None) -> str:
    """Return a plain-English cadence, falling back to the raw string.

    Supports the shapes this project actually stores — ``M H * * *`` with either a
    fixed hour or a ``*/N`` step on either field. Anything more exotic (lists,
    ranges, named months) is returned unchanged rather than guessed at, so the
    dashboard never claims something the scheduler is not actually doing.
    """
    raw = (expression or "").strip()
    if not raw:
        return "not scheduled"

    fields = raw.split()
    if len(fields) != 5:
        return raw

    minute, hour, day, month, weekday = fields
    # Anything calendar-specific is out of scope; don't try to narrate it.
    if month != "*" or weekday != "*" or day != "*":
        return raw

    minute_step = _step_of(minute)
    hour_step = _step_of(hour)

    # "*/N * * * *" — a sub-hourly cadence.
    if minute_step is not None and minute_step < 60:
        if hour == "*" and hour_step is None:
            return "every 15 minutes" if minute_step == 15 else f"every {minute_step} minutes"
        return raw

    # "M */N * * *" — the shape this project seeds.
    if hour_step is not None:
        if minute == "0":
            return "hourly" if hour_step == 1 else f"every {hour_step} hours"
        return f"every {hour_step} hours"

    # "M H * * *" — a fixed daily slot.
    try:
        hour_value = int(hour)
        minute_value = int(minute)
    except ValueError:
        return raw
    if not (0 <= hour_value <= 23 and 0 <= minute_value <= 59):
        return raw

    name = _HOUR_NAMES[hour_value]
    if minute_value == 0:
        return f"daily at {name}"
    return f"daily at {name}:{minute_value:02d}"
