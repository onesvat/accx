# Relative Reset Times Design

## Goal

Make imminent reset times easier to scan without losing the exact local time.

## Output

A future reset on the current local calendar day will use `HH:MM (Xh Ym)`,
such as `20:15 (2h 15m)`. The date is redundant for same-day values and will
not be printed.

Resets on another local calendar day will retain `YYYY-MM-DD HH:MM`, even when
they are less than 24 hours away. Past same-day values will show `HH:MM`
without a negative relative duration. Missing or invalid values remain `?`.

Relative durations will round up to the next whole minute. Zero-valued units
will be omitted, producing forms such as `15m`, `2h`, and `2h 15m`.

## Implementation

`format_reset_time` will accept an optional current time for deterministic
tests. Production callers will continue omitting it and use the current local
time. The formatter will compare local dates, calculate future same-day
durations, and return the appropriate presentation string. Fetching, caching,
and provider parsing will remain unchanged.

## Tests

Tests will cover same-day future, next-day, same-day past, minute rounding,
invalid values, and existing Claude/Codex list integration.
