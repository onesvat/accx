# List Reset Times Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show Claude and Codex five-hour and seven-day reset times in the profile list using the machine's local time zone.

**Architecture:** Add one presentation helper that normalizes provider reset values and formats them in local time. Reuse the reset values already returned by `usage_cache_values` and add them to the existing list table without changing API fetching or caching.

**Tech Stack:** Python 3 standard library, `unittest`

---

### Task 1: Format provider reset values

**Files:**
- Modify: `tests/test_accx.py`
- Modify: `accx:796-832`

- [ ] **Step 1: Write the failing formatting tests**

Add tests that calculate the expected local display value with Python's own
timezone conversion, then verify ISO and Unix inputs plus invalid input:

```python
def test_reset_times_are_formatted_in_local_time(self):
    epoch = 1782666000
    expected = datetime.fromtimestamp(epoch, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    self.assertEqual(ACCX["format_reset_time"](epoch), expected)
    self.assertEqual(ACCX["format_reset_time"]("2026-06-28T17:00:00Z"), datetime(
        2026, 6, 28, 17, 0, tzinfo=timezone.utc
    ).astimezone().strftime("%Y-%m-%d %H:%M"))
    self.assertEqual(ACCX["format_reset_time"]("invalid"), "?")
    self.assertEqual(ACCX["format_reset_time"](None), "?")
```

- [ ] **Step 2: Run the formatting test and verify RED**

Run:

```bash
python -m unittest discover -s tests -p 'test_accx.py' -k reset_times_are_formatted_in_local_time -v
```

Expected: error because `format_reset_time` does not exist.

- [ ] **Step 3: Implement the formatter**

Add after `reset_value_to_iso`:

```python
def format_reset_time(value: Any) -> str:
    normalized = reset_value_to_iso(value)
    parsed = parse_iso_datetime(normalized)
    if parsed is None:
        return "?"
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
```

- [ ] **Step 4: Use the formatter for both providers**

Change the reset values returned by `usage_cache_values`:

```python
format_reset_time(five.get("resets_at")),
format_reset_time(seven.get("resets_at")),
```

and:

```python
format_reset_time(primary.get("reset_at")),
format_reset_time(secondary.get("reset_at")),
```

- [ ] **Step 5: Run the formatting test and verify GREEN**

Run:

```bash
python -m unittest discover -s tests -p 'test_accx.py' -k reset_times_are_formatted_in_local_time -v
```

Expected: pass.

### Task 2: Print reset columns in the list table

**Files:**
- Modify: `tests/test_accx.py`
- Modify: `accx:1256-1289`

- [ ] **Step 1: Write the failing list output test**

Create a temporary Claude profile with cached ISO reset values, capture
`list_command` output, and assert the headers and local timestamps are present:

```python
def test_list_prints_reset_columns_and_values(self):
    five_reset = "2026-06-28T17:00:00Z"
    seven_reset = "2026-07-02T09:30:00Z"
    expected_five = datetime(2026, 6, 28, 17, 0, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    expected_seven = datetime(2026, 7, 2, 9, 30, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ACCX_HOME": temp}):
        profile_dir = Path(temp) / "claude" / "work"
        profile_dir.mkdir(parents=True)
        (profile_dir / "credential.json").write_text(json.dumps({
            "claudeAiOauth": {"accessToken": "access"}
        }))
        (profile_dir / "meta.json").write_text(json.dumps({
            "identity": {"email": "work@example.com", "plan": "pro"},
            "credential": {},
        }))
        (profile_dir / ".usage-cache.json").write_text(json.dumps({"raw": {
            "five_hour": {"utilization": 10, "resets_at": five_reset},
            "seven_day": {"utilization": 20, "resets_at": seven_reset},
        }}))
        output = io.StringIO()
        with redirect_stdout(output), patch.dict(
            ACCX["list_command"].__globals__, {"detect_active_profile": Mock(return_value=None)}
        ):
            ACCX["list_command"](ACCX["Provider"]("claude"), False)

    rendered = output.getvalue()
    self.assertIn("5H RESET", rendered)
    self.assertIn("7D RESET", rendered)
    self.assertIn(expected_five, rendered)
    self.assertIn(expected_seven, rendered)
```

Also import:

```python
import io
from contextlib import redirect_stdout
```

- [ ] **Step 2: Run the output test and verify RED**

Run:

```bash
python -m unittest discover -s tests -p 'test_accx.py' -k list_prints_reset_columns_and_values -v
```

Expected: failure because the reset headers and values are absent.

- [ ] **Step 3: Print the reset columns**

Retain all four values from `usage_cache_values` and render them:

```python
print(
    f"  {C.bold}{'PROFILE':14} {'EMAIL':28} {'PLAN':10} {'EXP':20} "
    f"{'5H%':>6} {'5H RESET':16} {'7D%':>6} {'7D RESET':16}{C.off}"
)
```

```python
p5, p7, r5, r7 = usage_cache_values(
    provider, profile, use_api, cred, active=profile == active
)
```

```python
print(
    f"  {marker}{profile[:13]:13} {C.dim}{email:28}{C.off} {plan:10} "
    f"{exp:20} {p5:>5}% {r5:16} {p7:>5}% {r7:16}"
)
```

- [ ] **Step 4: Run the output test and verify GREEN**

Run:

```bash
python -m unittest discover -s tests -p 'test_accx.py' -k list_prints_reset_columns_and_values -v
```

Expected: pass.

### Task 3: Verify the complete change

**Files:**
- Verify: `accx`
- Verify: `tests/test_accx.py`
- Verify: `README.md`

- [ ] **Step 1: Run all tests**

Run:

```bash
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Check syntax and whitespace**

Run:

```bash
python -m py_compile accx tests/test_accx.py
git diff --check
```

Expected: both commands exit successfully with no output.

- [ ] **Step 3: Confirm documentation remains accurate**

Verify that README's existing description, “Table of saved accounts with usage
percentages and reset times,” matches the implemented output. No README change
is required.

- [ ] **Step 4: Commit the implementation**

```bash
git add accx tests/test_accx.py docs/superpowers/plans/2026-06-28-list-reset-times.md
git commit -m "feat: show usage reset times in profile list"
```
