# Notes (fix later)

## Context
- Repo: `Lecture-Day-10/`
- Topic: Day 10 lab — data pipeline + eval evidence

## Issue to revisit: Sprint 3 "inject-bad" vs cleaning quarantine

### Symptom
Sprint 3 guidance suggests running:
- `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`
to intentionally keep the stale refund window ("14 ngày") so expectations fail and before/after eval is measurable.

However, after recent updates, `transform/cleaning_rules.py` quarantines any `policy_refund_v4` chunk containing "14 ngày" (stale refund), which removes it from `cleaned_*` even in demo/inject mode. That makes:
- `quality/expectations.py` check `refund_no_stale_14d_window` always pass (because the offending chunk never reaches cleaned), and
- `eval_retrieval.py` less able to show a clear before/after on `q_refund_window`.

### Desired behavior
- Normal mode (`etl_pipeline.py run`): auto-fix 14→7 so pipeline can proceed cleanly.
- Demo mode (`--no-refund-fix`): keep "14 ngày" in cleaned (or at least keep it embeddable) so expectation/eval can demonstrate failure before fix.

### Candidate fix (later)
In `transform/cleaning_rules.py`:
- Do NOT quarantine stale refund chunk when `apply_refund_window_fix=False`.
- Instead, mark `metrics.has_stale_refund=True` and let `etl_pipeline.py` / expectations control halt vs demo behavior.

### Why postponed
Need team alignment: this changes the inject/canonical semantics and may affect rubric interpretation. Decide in group before merging.

