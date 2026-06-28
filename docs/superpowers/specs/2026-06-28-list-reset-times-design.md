# List Reset Times Design

## Goal

Show the five-hour and seven-day usage reset times in `accx claude list --api`
and `accx codex list --api`.

## Output

The profile table will add `5H RESET` and `7D RESET` columns adjacent to their
usage percentage columns. Reset timestamps will use the machine's local time
zone and the unambiguous `YYYY-MM-DD HH:MM` format. Missing or invalid values
will display as `?`.

The columns will also appear when cached usage is shown so that API and cached
tables keep the same layout. In API mode they contain freshly fetched values;
otherwise they contain the saved values, if available.

## Data Flow

The existing provider-specific parsing remains responsible for reading Claude's
ISO timestamps and Codex's Unix timestamps. A presentation helper will convert
either representation into local display time. `list_command` will retain and
print the two reset values currently returned and discarded by
`usage_cache_values`.

## Error Handling

An absent, unknown, or unparsable reset value will not fail the list command. It
will be rendered as `?`.

## Tests

Unit tests will cover:

- Claude ISO reset values converted to local time.
- Codex Unix reset values converted to local time.
- Missing or invalid reset values rendered as `?`.
- The list table containing both reset column headers and reset values.
