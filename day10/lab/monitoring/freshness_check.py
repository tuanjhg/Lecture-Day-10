"""
Kiểm tra freshness từ manifest pipeline (SLA đơn giản theo giờ).

Sprint 4 — Long (Quality & Observability):
  • Dual-boundary freshness: ingest + publish
  • WARN level (sắp hết SLA) ngoài PASS/FAIL
  • Đọc SLA từ contract / env
  • CLI-friendly output format
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# ── Timestamp parsing ─────────────────────────────────────────

def parse_iso(ts: str) -> datetime | None:
    """Parse ISO 8601 timestamp, tolerating 'Z' suffix and missing timezone."""
    if not ts:
        return None
    try:
        # Cho phép "2026-04-10T08:00:00" không có timezone
        if ts.endswith("Z"):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


# ── Core freshness check ──────────────────────────────────────

def check_manifest_freshness(
    manifest_path: Path,
    *,
    sla_hours: float = 24.0,
    grace_period_hours: float = 2.0,
    now: datetime | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """
    Trả về ("PASS" | "WARN" | "FAIL", detail dict).

    Thresholds (per contract v2.0):
      PASS: age_hours <= sla_hours
      WARN: sla_hours < age_hours <= sla_hours + grace_period_hours
      FAIL: age_hours > sla_hours + grace_period_hours
    """
    now = now or datetime.now(timezone.utc)
    if not manifest_path.is_file():
        return "FAIL", {"reason": "manifest_missing", "path": str(manifest_path)}

    data: Dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    ts_raw = data.get("latest_exported_at") or data.get("run_timestamp")
    dt = parse_iso(str(ts_raw)) if ts_raw else None
    if dt is None:
        return "WARN", {"reason": "no_timestamp_in_manifest", "manifest": data}

    age_hours = (now - dt).total_seconds() / 3600.0
    detail: Dict[str, Any] = {
        "latest_exported_at": ts_raw,
        "age_hours": round(age_hours, 3),
        "sla_hours": sla_hours,
        "grace_period_hours": grace_period_hours,
        "boundary": "publish",
    }

    if age_hours <= sla_hours:
        return "PASS", detail
    elif age_hours <= sla_hours + grace_period_hours:
        return "WARN", {**detail, "reason": "approaching_sla_limit"}
    return "FAIL", {**detail, "reason": "freshness_sla_exceeded"}


# ── Dual-boundary freshness (Sprint 4 — Long) ────────────────

def check_dual_boundary_freshness(
    manifest_path: Path,
    *,
    sla_hours: float = 24.0,
    grace_period_hours: float = 2.0,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """
    Đo freshness tại 2 boundary: ingest (exported_at) và publish (run_timestamp).

    Per contract v2.0 :: freshness.ingest_boundary + publish_boundary.
    Giúp phát hiện bottleneck: data ingest fresh nhưng publish chậm (hoặc ngược lại).

    Returns dict with:
      - ingest_status, ingest_detail
      - publish_status, publish_detail
      - pipeline_latency_minutes (thời gian từ ingest → publish)
      - overall_status (worst of the two)
    """
    now = now or datetime.now(timezone.utc)
    result: Dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "check_time": now.isoformat(),
        "sla_hours": sla_hours,
    }

    if not manifest_path.is_file():
        result["overall_status"] = "FAIL"
        result["reason"] = "manifest_missing"
        return result

    data: Dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    # ── Boundary 1: Ingest (exported_at = khi data được export từ source) ──
    ingest_ts = parse_iso(str(data.get("latest_exported_at", "")))
    if ingest_ts:
        ingest_age = (now - ingest_ts).total_seconds() / 3600.0
        if ingest_age <= sla_hours:
            ingest_status = "PASS"
        elif ingest_age <= sla_hours + grace_period_hours:
            ingest_status = "WARN"
        else:
            ingest_status = "FAIL"
        result["ingest"] = {
            "status": ingest_status,
            "timestamp": data.get("latest_exported_at"),
            "age_hours": round(ingest_age, 3),
        }
    else:
        ingest_status = "WARN"
        result["ingest"] = {"status": "WARN", "reason": "no_exported_at"}

    # ── Boundary 2: Publish (run_timestamp = khi pipeline chạy xong) ──
    publish_ts = parse_iso(str(data.get("run_timestamp", "")))
    if publish_ts:
        publish_age = (now - publish_ts).total_seconds() / 3600.0
        if publish_age <= sla_hours:
            publish_status = "PASS"
        elif publish_age <= sla_hours + grace_period_hours:
            publish_status = "WARN"
        else:
            publish_status = "FAIL"
        result["publish"] = {
            "status": publish_status,
            "timestamp": data.get("run_timestamp"),
            "age_hours": round(publish_age, 3),
        }
    else:
        publish_status = "WARN"
        result["publish"] = {"status": "WARN", "reason": "no_run_timestamp"}

    # ── Pipeline latency (ingest → publish) ──
    if ingest_ts and publish_ts:
        latency_minutes = (publish_ts - ingest_ts).total_seconds() / 60.0
        result["pipeline_latency_minutes"] = round(latency_minutes, 2)

    # ── Overall = worst status ──
    status_order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    worst = min(
        [ingest_status, publish_status],
        key=lambda s: status_order.get(s, 1),
    )
    result["overall_status"] = worst

    # ── Record counts from manifest ──
    for key in ("raw_records", "cleaned_records", "quarantine_records", "run_id"):
        if key in data:
            result[key] = data[key]

    return result


# ── Per-source SLA check (Sprint 4 — Long) ───────────────────

# Source SLA from contract v2.0 :: source_sla
SOURCE_SLA: Dict[str, float] = {
    "policy_refund_v4": 12.0,
    "hr_leave_policy": 48.0,
    "it_helpdesk_faq": 24.0,
    "sla_p1_2026": 720.0,
}


def check_source_sla_compliance(
    manifest_path: Path,
    *,
    now: datetime | None = None,
) -> Dict[str, Any]:
    """
    Kiểm tra SLA riêng cho từng source (per contract v2.0 :: source_sla).

    Returns dict mapping doc_id → {status, lag_hours, sla_hours}.
    """
    now = now or datetime.now(timezone.utc)
    result: Dict[str, Any] = {}

    if not manifest_path.is_file():
        return {"error": "manifest_missing"}

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    exported_at = parse_iso(str(data.get("latest_exported_at", "")))

    if not exported_at:
        return {"error": "no_exported_at_in_manifest"}

    age_hours = (now - exported_at).total_seconds() / 3600.0

    for doc_id, sla_hours in SOURCE_SLA.items():
        if age_hours <= sla_hours:
            status = "PASS"
        else:
            status = "FAIL"
        result[doc_id] = {
            "status": status,
            "age_hours": round(age_hours, 3),
            "sla_hours": sla_hours,
        }

    return result


# ── Pretty print helper ──────────────────────────────────────

def format_freshness_report(dual_result: Dict[str, Any]) -> str:
    """Format dual-boundary freshness result for CLI output."""
    lines = []
    overall = dual_result.get("overall_status", "UNKNOWN")
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "🔴"}.get(overall, "❓")

    lines.append(f"{icon} Overall Freshness: {overall}")
    lines.append(f"   SLA: {dual_result.get('sla_hours', '?')}h")

    if "run_id" in dual_result:
        lines.append(f"   Run ID: {dual_result['run_id']}")

    for boundary in ("ingest", "publish"):
        info = dual_result.get(boundary, {})
        b_status = info.get("status", "N/A")
        b_icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "🔴"}.get(b_status, "❓")
        age = info.get("age_hours", "?")
        lines.append(f"   {boundary.capitalize():8s}: {b_icon} {b_status} (age={age}h)")

    if "pipeline_latency_minutes" in dual_result:
        lines.append(f"   Pipeline latency: {dual_result['pipeline_latency_minutes']}min")

    for key in ("raw_records", "cleaned_records", "quarantine_records"):
        if key in dual_result:
            lines.append(f"   {key}: {dual_result[key]}")

    return "\n".join(lines)
