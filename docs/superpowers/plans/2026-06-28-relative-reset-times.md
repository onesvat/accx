# Relative Reset Times Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show exact time plus a relative duration for future resets on the current local calendar day.

**Architecture:** Extend the existing reset presentation helper with an injectable current time. Keep provider parsing, caching, and table rendering unchanged.

**Tech Stack:** Python 3 standard library, `unittest`

---

### Task 1: Format same-day resets relatively

**Files:**
- Modify: `tests/test_accx.py:112-214`
- Modify: `accx:805-810`

- [ ] **Step 1: Write the failing formatter test**

Use a fixed local current time and assert future same-day, next-day, past
same-day, numeric, and invalid values:

```python
local_tz = datetime.now().astimezone().tzinfo
now = datetime(2026, 6, 28, 18, 0, 30, tzinfo=local_tz)

self.assertEqual(
    format_reset_time("2026-06-28T20:15:00+03:00", now=now),
    "20:15 (2h 15m)",
)
self.assertEqual(
    format_reset_time("2026-06-29T01:00:00+03:00", now=now),
    "2026-06-29 01:00",
)
self.assertEqual(
    format_reset_time("2026-06-28T17:00:00+03:00", now=now),
    "17:00",
)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest discover -s tests -p 'test_accx.py' -k reset_times_are_formatted_in_local_time -v
```

Expected: error because `format_reset_time` does not accept `now`.

- [ ] **Step 3: Implement local relative formatting**

```python
def format_reset_time(value: Any, now: datetime | None = None) -> str:
    normalized = reset_value_to_iso(value)
    parsed = parse_iso_datetime(normalized)
    if parsed is None:
        return "?"
    reset = parsed.astimezone()
    current = (now or datetime.now().astimezone()).astimezone()
    if reset.date() != current.date():
        return reset.strftime("%Y-%m-%d %H:%M")
    absolute = reset.strftime("%H:%M")
    remaining_seconds = (reset - current).total_seconds()
    if remaining_seconds <= 0:
        return absolute
    remaining_minutes = math.ceil(remaining_seconds / 60)
    hours, minutes = divmod(remaining_minutes, 60)
    parts = ([f"{hours}h"] if hours else []) + ([f"{minutes}m"] if minutes else [])
    return f"{absolute} ({' '.join(parts)})"
```

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python -m unittest discover -s tests -p 'test_accx.py' -k ListUsageTests -v
```

Expected: all list usage tests pass.

### Task 2: Verify and commit

**Files:**
- Verify: `accx`
- Verify: `tests/test_accx.py`

- [ ] **Step 1: Check syntax and whitespace**

```bash
python -m py_compile accx tests/test_accx.py
git diff --check
```

- [ ] **Step 2: Run the complete suite**

```bash
python -m unittest discover -s tests -v
```

Expected: the relative reset tests pass; the two pre-existing Dashboard HTTP
`bind_host` errors remain unchanged.

- [ ] **Step 3: Commit**

```bash
git add accx tests/test_accx.py docs/superpowers/plans/2026-06-28-relative-reset-times.md
git commit -m "feat: show relative time for same-day resets"
```
