"""
Cleaning rules — raw export → cleaned rows + quarantine.

Integrated from contracts/data_contract.yaml v2.0:
  • Schema validation (min_length 8, required fields)
  • Quality rules (no_duplicate_chunk_id, no_stale_refund_window, etc.)
  • Version resolution (keep newest by effective_date, then exported_at)
  • Freshness & canonical sources (from canonical_sources list)

Metrics tracking:
  - Each rule logs count of records affected (quarantined, dropped, fixed)
  - Halt conditions: stale_refund_window (if apply_refund_window_fix=True)
  - Dedup by chunk_id + exported_at (prefer latest version)

New rules (Sprint 2 — Long & Hải):
  • no_bom_encoding: BOM/control chars → quarantine
  • no_excessive_whitespace: >3 spaces → normalize
  • exported_at_not_future: future timestamps → quarantine
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# From contracts/data_contract.yaml :: allowed_doc_ids
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
    }
)

# Quality rules from contract
MIN_CHUNK_TEXT_LENGTH = 8

# Policy versioning from contract :: policy_versioning section
HR_LEAVE_MIN_EFFECTIVE_DATE = "2026-01-01"
REFUND_WINDOW_CANONICAL = "7 ngày"  # v4 canonical; v3 "14 ngày" → halt if present

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _norm_text(s: str) -> str:
    """Normalize text for dedup: lowercase + trim multiple spaces."""
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    """
    Generate stable chunk_id from doc_id + seq + hash(chunk_text).
    Idempotent: same input → same output.
    Format: {doc_id}_{seq}_{hash[:16]}
    """
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Normalize effective_date to ISO 8601 (YYYY-MM-DD).
    
    Supports:
    - ISO 8601 (YYYY-MM-DD) → pass through
    - DD/MM/YYYY → convert to ISO
    - Empty/NULL → error
    - Invalid format → error
    
    Returns: (iso_date_string, error_reason_or_empty)
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SLASH.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    """Load raw CSV; trim whitespace from all fields."""
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


# ── New rule helpers (Sprint 2 — Long) ────────────────────────

# BOM and control character pattern (contract rule: no_bom_encoding)
_BOM_CONTROL_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"  # C0 control chars (except \t \n \r)
    r"|\xef\xbb\xbf"                         # UTF-8 BOM
)

# Excessive whitespace pattern (contract rule: no_excessive_whitespace)
_EXCESSIVE_WHITESPACE = re.compile(r"[ \t]{4,}|\n{3,}")


def _has_bom_or_control(text: str) -> bool:
    """Check if text contains BOM or control characters (contract: no_bom_encoding)."""
    return bool(_BOM_CONTROL_PATTERN.search(text))


def _normalize_whitespace(text: str) -> tuple[str, bool]:
    """
    Normalize excessive whitespace in chunk_text (contract: no_excessive_whitespace).
    Returns (normalized_text, was_modified).
    """
    original = text
    # Collapse >3 consecutive spaces/tabs into single space
    text = re.sub(r"[ \t]{4,}", " ", text)
    # Collapse >2 consecutive newlines into double newline
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Final trim
    text = text.strip()
    return text, text != original


def _is_future_timestamp(exported_at: str, tolerance_hours: float = 1.0) -> bool:
    """
    Check if exported_at is in the future (contract: exported_at_not_future).
    Allows tolerance_hours grace for minor clock skew.
    """
    if not exported_at:
        return False
    try:
        ts = exported_at.strip()
        if ts.endswith("Z"):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff_hours = (dt - now).total_seconds() / 3600.0
        return diff_hours > tolerance_hours
    except (ValueError, TypeError):
        return False


class CleaningMetrics:
    """Track impact of each quality rule for anti-trivial verification."""

    def __init__(self):
        self.metrics: Dict[str, int] = {
            "raw_records": 0,
            "quarantine_unknown_doc_id": 0,
            "quarantine_missing_effective_date": 0,
            "quarantine_invalid_date_format": 0,
            "quarantine_stale_hr_policy": 0,
            "quarantine_short_chunk_text": 0,
            "quarantine_empty_chunk_text": 0,
            "stale_refund_window_detected": 0,
            # New rules (Sprint 2 — Long)
            "quarantine_bom_encoding": 0,
            "quarantine_future_exported_at": 0,
            "cleaned_excessive_whitespace_fixed": 0,
            "dropped_duplicate_chunk_id": 0,
            "dropped_duplicate_chunk_text": 0,
            "cleaned_refund_window_fixed": 0,
            "cleaned_records": 0,
        }
        self.has_stale_refund = False

    def record(self, key: str, count: int = 1):
        """Increment metric."""
        if key in self.metrics:
            self.metrics[key] += count
        else:
            # Auto-register new metrics
            self.metrics[key] = count

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.metrics.items() if v > 0}
        d["has_stale_refund"] = self.has_stale_refund
        return d


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Ingest → clean → validate per contract.

    Per-row rules (from contracts/data_contract.yaml :: quality_rules):
    1. Dedup by chunk_id: keep latest by exported_at (warn severity)
    2. Unknown doc_id: quarantine (error severity)
    3. Missing/invalid effective_date: quarantine (error severity)
    4. HR policy stale version (effective_date < 2026-01-01): quarantine (error severity)
    5. Short/empty chunk_text (<8 chars): quarantine/drop (error severity)
    6. Stale refund window (doc_id=policy_refund_v4 + contains "14 ngày"): quarantine + mark halt (halt severity)
    7. Duplicate chunk_text (semantic): drop excess (warn severity)

    If apply_refund_window_fix=True: also fix "14 ngày" → "7 ngày" for cleaned records.
    If stale refund detected AND apply_refund_window_fix=False: return metrics with has_stale_refund=True
    so the pipeline can decide to halt (or run in demo mode).

    Returns: (cleaned, quarantine, metrics)
    """
    metrics = CleaningMetrics()
    metrics.record("raw_records", len(rows))

    # Step 1: Dedup by chunk_id — keep latest by exported_at
    # (Per contract:: duplicate_chunk_id rule = "DROP tất cả except latest")
    chunk_id_map: Dict[str, Dict[str, str]] = {}
    for raw in rows:
        chunk_id = raw.get("chunk_id", "")
        if chunk_id and chunk_id in chunk_id_map:
            # Prefer later exported_at
            prev = chunk_id_map[chunk_id]
            prev_ts = prev.get("exported_at", "")
            curr_ts = raw.get("exported_at", "")
            if curr_ts >= prev_ts:  # lexicographic comparison for ISO timestamp
                metrics.record("dropped_duplicate_chunk_id")
                chunk_id_map[chunk_id] = raw
            else:
                metrics.record("dropped_duplicate_chunk_id")
        else:
            chunk_id_map[chunk_id] = raw

    # Step 2: Per-row validation & cleaning
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    for raw in chunk_id_map.values():
        doc_id = raw.get("doc_id", "")
        chunk_id = raw.get("chunk_id", "")
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        # Rule: unknown_doc_id (error)
        if doc_id not in ALLOWED_DOC_IDS:
            metrics.record("quarantine_unknown_doc_id")
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        # Rule: invalid/missing effective_date (error)
        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            metrics.record("quarantine_missing_effective_date")
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            metrics.record("quarantine_invalid_date_format")
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        # Rule: stale HR policy (effective_date < 2026-01-01) (error)
        # Per contract:: version_resolution.rule = "Select newest by effective_date"
        if doc_id == "hr_leave_policy" and eff_norm < HR_LEAVE_MIN_EFFECTIVE_DATE:
            metrics.record("quarantine_stale_hr_policy")
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        # Rule: empty/short chunk_text (error)
        # Per contract:: schema_cleaned.chunk_text.constraints.min_length = 8
        if not text or len(text) < MIN_CHUNK_TEXT_LENGTH:
            if not text:
                metrics.record("quarantine_empty_chunk_text")
            else:
                metrics.record("quarantine_short_chunk_text")
            quarantine.append({**raw, "reason": "insufficient_chunk_text_length"})
            continue

        # ── New Rule (Sprint 2 — Long): BOM / control character detection ──
        # Per contract v2.0:: quality_rules.no_bom_encoding.severity = "error"
        # BOM (\xef\xbb\xbf) gây lỗi embedding distance; control chars gây parse error
        if _has_bom_or_control(text):
            metrics.record("quarantine_bom_encoding")
            quarantine.append({**raw, "reason": "bom_or_control_chars_detected"})
            continue

        # ── New Rule (Sprint 2 — Long): Future exported_at detection ──
        # Per contract v2.0:: quality_rules.exported_at_not_future.severity = "error"
        # exported_at in the future indicates data tampering or clock drift
        if _is_future_timestamp(exported_at):
            metrics.record("quarantine_future_exported_at")
            quarantine.append({**raw, "reason": "exported_at_is_future"})
            continue

        # Start from (potentially) cleaned text, then apply policy fixes.
        fixed_text = text

        # ── New Rule (Sprint 2 — Long): Excessive whitespace normalization ──
        # Per contract v2.0:: quality_rules.no_excessive_whitespace.severity = "warn"
        # Whitespace thừa làm embedding distance bị lệch
        fixed_text, ws_fixed = _normalize_whitespace(fixed_text)
        if ws_fixed:
            metrics.record("cleaned_excessive_whitespace_fixed")

        # Rule: stale refund window (supports both normal & demo mode)
        #
        # Normal mode (apply_refund_window_fix=True):
        #   - Fix 14→7 and keep in cleaned so Sprint 2 can embed a correct index.
        #
        # Demo mode (apply_refund_window_fix=False, used with --no-refund-fix):
        #   - Keep "14 ngày" so expectations/eval can observe a failure scenario (Sprint 3).
        if doc_id == "policy_refund_v4" and "14 ngày" in fixed_text:
            metrics.record("stale_refund_window_detected")
            if apply_refund_window_fix:
                fixed_text = (
                    fixed_text.replace("14 ngày làm việc", "7 ngày làm việc")
                    .replace("14 ngày", "7 ngày")
                    + " [cleaned: stale_refund_window_fixed]"
                )
                metrics.record("cleaned_refund_window_fixed")
            else:
                metrics.has_stale_refund = True

        # Rule: duplicate chunk_text (warn)
        # Per contract:: rule = "keep first occurrence; DROP others"
        key = _norm_text(fixed_text)
        if key in seen_text:
            metrics.record("dropped_duplicate_chunk_text")
            continue
        seen_text.add(key)

        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    metrics.record("cleaned_records", len(cleaned))
    return cleaned, quarantine, metrics.to_dict()


def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """Write cleaned CSV with schema from contract (chunk_id, doc_id, chunk_text, effective_date, exported_at)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    """
    Write quarantine CSV with all fields from raw + reason.
    
    Per contract:: Quarantine location: artifacts/quarantine/quarantine_<run-id>.csv
    — reviewed weekly, approval required before merge.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
