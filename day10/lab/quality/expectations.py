"""
Expectation suite đơn giản (không bắt buộc Great Expectations).

Sinh viên có thể thay bằng GE / pydantic / custom — miễn là có halt có kiểm soát.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str  # "warn" | "halt"
    detail: str


def run_expectations(cleaned_rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    """
    Trả về (results, should_halt).

    should_halt = True nếu có bất kỳ expectation severity halt nào fail.
    """
    results: List[ExpectationResult] = []

    # E1: có ít nhất 1 dòng sau clean
    ok = len(cleaned_rows) >= 1
    results.append(
        ExpectationResult(
            "min_one_row",
            ok,
            "halt",
            f"cleaned_rows={len(cleaned_rows)}",
        )
    )

    # E2: không doc_id rỗng
    bad_doc = [r for r in cleaned_rows if not (r.get("doc_id") or "").strip()]
    ok2 = len(bad_doc) == 0
    results.append(
        ExpectationResult(
            "no_empty_doc_id",
            ok2,
            "halt",
            f"empty_doc_id_count={len(bad_doc)}",
        )
    )

    # E3: policy refund không được chứa cửa sổ sai 14 ngày (sau khi đã fix)
    bad_refund = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "policy_refund_v4"
        and "14 ngày làm việc" in (r.get("chunk_text") or "")
    ]
    ok3 = len(bad_refund) == 0
    results.append(
        ExpectationResult(
            "refund_no_stale_14d_window",
            ok3,
            "halt",
            f"violations={len(bad_refund)}",
        )
    )

    # E4: chunk_text đủ dài
    short = [r for r in cleaned_rows if len((r.get("chunk_text") or "")) < 8]
    ok4 = len(short) == 0
    results.append(
        ExpectationResult(
            "chunk_min_length_8",
            ok4,
            "warn",
            f"short_chunks={len(short)}",
        )
    )

    # E7: không có doc_id ngoài danh sách cho phép
    allowed_doc_ids = {"policy_refund_v4", "sla_p1_2026", "it_helpdesk_faq", "hr_leave_policy"}
    bad_docid = [r for r in cleaned_rows if r.get("doc_id") not in allowed_doc_ids]
    ok7 = len(bad_docid) == 0
    results.append(
        ExpectationResult(
            "no_unknown_doc_id",
            ok7,
            "halt",
            f"unknown_doc_id_count={len(bad_docid)}",
        )
    )

    # E8: không có chunk_id trùng lặp
    seen_chunk_ids = set()
    dup_chunk_ids = set()
    for r in cleaned_rows:
        cid = r.get("chunk_id")
        if cid in seen_chunk_ids:
            dup_chunk_ids.add(cid)
        else:
            seen_chunk_ids.add(cid)
    ok8 = len(dup_chunk_ids) == 0
    results.append(
        ExpectationResult(
            "no_duplicate_chunk_id",
            ok8,
            "halt",
            f"duplicate_chunk_ids={list(dup_chunk_ids)}",
        )
    )

    # E5: effective_date đúng định dạng ISO sau clean (phát hiện parser lỏng)
    iso_bad = [
        r
        for r in cleaned_rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or "").strip())
    ]
    ok5 = len(iso_bad) == 0
    results.append(
        ExpectationResult(
            "effective_date_iso_yyyy_mm_dd",
            ok5,
            "halt",
            f"non_iso_rows={len(iso_bad)}",
        )
    )

    # E6: không còn marker phép năm cũ 10 ngày trên doc HR (conflict version sau clean)
    bad_hr_annual = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "hr_leave_policy"
        and "10 ngày phép năm" in (r.get("chunk_text") or "")
    ]
    ok6 = len(bad_hr_annual) == 0
    results.append(
        ExpectationResult(
            "hr_leave_no_stale_10d_annual",
            ok6,
            "halt",
            f"violations={len(bad_hr_annual)}",
        )
    )
    
    # E9: chunk_text không được rỗng (Content rỗng -> REJECT)
    # Đây là chốt chặn đảm bảo core logic không xử lý các document vô giá trị.
    empty_content = [r for r in cleaned_rows if not (r.get("chunk_text") or "").strip()]
    ok9 = len(empty_content) == 0
    results.append(
        ExpectationResult(
            "no_empty_chunk_text",
            ok9,
            "halt",
            f"empty_chunk_count={len(empty_content)}",
        )
    )

    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
