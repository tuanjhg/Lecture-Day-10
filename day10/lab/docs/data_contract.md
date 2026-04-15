# Data Contract — Lab Day 10

> Đồng bộ từ `contracts/data_contract.yaml` v2.0 — cập nhật bởi Long (Quality & Observability).
> 
> **Last updated:** 2026-04-15 | **Author:** Long | **Reviewer:** Hải, Dũng

---

## 1. Nguồn dữ liệu (Source Map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert | Owner | Priority |
|-------|-------------------|-------------------|----------------|-------|----------|
| **policy_refund_v4** | CSV export từ Document Management System | Migration error: chunk_id=3 có text "14 ngày" (từ v3 cũ) thay vì "7 ngày" canonical; duplicate chunks (id 1-2 giống nhau) | Quarantine chunk với text chứa "14 ngày"; `quarantine_stale_refund_window > 0` là alert | Policy Team | **High** |
| **hr_leave_policy** | CSV export từ HR Management System | Version conflict: 2 bản (row 7: "10 ngày" HR 2025, row 8: "12 ngày" HR 2026); effective_date < 2026-01-01 → stale | Chọn version mới nhất theo effective_date ≥ 2026-01-01; `quarantine_stale_hr_policy` | HR Team | Medium |
| **it_helpdesk_faq** | CSV export từ Knowledge Base | Date format inconsistency: chunk_id=10 có effective_date="01/02/2026" (DD/MM/YYYY) thay vì ISO 8601 | Parse DD/MM/YYYY → ISO tự động; track `quarantine_invalid_date_format` | IT Service Desk | Medium |
| **sla_p1_2026** | CSV export từ SLA Policy DB | Single policy chunk; ít thay đổi | Verify chunk_text không empty; `p1_response_sla_minutes = 15` | Service Management | Low |
| **legacy_catalog_xyz_zzz** | CSV export từ Legacy system (deprecated) | Unknown source — không trong allowlist; obsolete | Quarantine 100% records; `quarantine_unknown_doc_id` | ⚠️ No owner | — |
| **unknown_security_doc** | CSV export (nguồn không xác định) | Tài liệu security chưa phê duyệt cho KB | Quarantine 100% records; `quarantine_unknown_doc_id` | ⚠️ Security Team review | — |

---

## 2. Schema Cleaned

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | ✅ | ID ổn định: `{doc_id}_{seq}_{hash[:16]}` — dùng làm key upsert ChromaDB |
| `doc_id` | string | ✅ | Enum: `{policy_refund_v4, hr_leave_policy, it_helpdesk_faq, sla_p1_2026}`; unknown → quarantine |
| `chunk_text` | string | ✅ | Min 8 chars; UTF-8; trim whitespace; normalize unicode |
| `effective_date` | date | ✅ | ISO 8601 (YYYY-MM-DD); parse "DD/MM/YYYY" → ISO; NULL → quarantine |
| `exported_at` | datetime | ✅ | ISO 8601 (UTC); từ ingest time; không modify |

---

## 3. Quy tắc Quarantine vs Drop

| # | Điều kiện | Action | Severity | Lý do | Approval để merge lại |
|---|----------|--------|----------|-------|----------------------|
| 1 | `chunk_text IS NULL` hoặc len < 8 | **DROP** | error | Text không đủ thông tin; không khôi phục được | Không cần (xóa vĩnh viễn) |
| 2 | `doc_id NOT IN allowlist` | **QUARANTINE** | error | Unknown source; cần verify | Data Owner duyệt metadata + source confirmation |
| 3 | `effective_date IS NULL` | **QUARANTINE** | error | Thiếu key metadata; không biết version nào active | Data Owner xác nhận version + backfill date |
| 4 | `effective_date` format invalid (trừ DD/MM/YYYY) | **QUARANTINE** | error | Parse error; cần check thủ công | DevOps check log + format correction |
| 5 | Text chứa "14 ngày" + `doc_id = policy_refund_v4` | **QUARANTINE + HALT** | **halt** | Stale refund window từ v3 migration | Policy Owner: confirm fix v4 = 7 ngày |
| 6 | Duplicate `chunk_id` | **DROP except latest** | warn | Dedup by chunk_id; giữ record mới nhất theo `exported_at` | Tự động; log `dropped_duplicate_chunk_id` |
| 7 | Duplicate `chunk_text` (semantic) | **DROP except first** | warn | Giảm noise vector store | Tự động; log `dropped_duplicate_chunk_text` |
| 8 | HR policy `effective_date < 2026-01-01` | **QUARANTINE** | error | Bản HR cũ (2025/2024) không còn hiệu lực | HR Team review |
| **9** *(new)* | BOM / control chars trong `chunk_text` | **QUARANTINE** | error | BOM gây lỗi embedding distance; control chars gây parse error | DevOps clean + re-ingest |
| **10** *(new)* | `exported_at` > now + 1h (tương lai) | **QUARANTINE** | error | Data tampered hoặc clock drift nghiêm trọng | Infra Team check NTP sync |
| **11** *(new)* | >3 spaces liên tiếp trong `chunk_text` | **NORMALIZE + WARN** | warn | Whitespace thừa làm embedding distance bị lệch | Tự động normalize |

**Quarantine location:** `artifacts/quarantine/quarantine_<run-id>.csv` — reviewed weekly bởi Long/Hải, approval từ Data Owner trước merge vào cleaned.

---

## 4. Phiên bản & Canonical

### 4.1 Source of Truth (Canonical)

| doc_id | Canonical file | Owner | Version | Note |
|--------|----------------|-------|---------|------|
| **policy_refund_v4** | `data/docs/policy_refund_v4.txt` | Policy Team | v4 (2026-02-01) | **Migration risk:** v3 chunks (refund 14 ngày) còn trong raw → quarantine + halt |
| **hr_leave_policy** | `data/docs/hr_leave_policy.txt` | HR Team | 2026 (2026-02-01+) | Prefer effective_date ≥ 2026-01-01; drop version 2025 (10 ngày) và 2024 |
| **it_helpdesk_faq** | `data/docs/it_helpdesk_faq.txt` | IT Service Desk | Latest | No versioning; reviewed weekly |
| **sla_p1_2026** | `data/docs/sla_p1_2026.txt` | Service Management | 2026 | Static policy; no changes expected |
| **access_control_sop** | `data/docs/access_control_sop.txt` | Security Team | Latest | Có trong docs nhưng chưa trong CSV export (có thể thêm vào allowlist) |

### 4.2 Version Resolution

- **HR Leave Policy conflict:** 2 versions (10 vs 12 ngày) + 1 bản 2024. **Canonical:** chỉ giữ `effective_date >= 2026-01-01` → drop row 7 (2025-01-01) và row 13 (2024-12-31).
- **Refund window conflict:** Chunk_id=3 có "14 ngày" từ migration lỗi v3. **Canonical:** policy_refund_v4 = 7 ngày → quarantine chunk_id=3 + fix trong cleaning_rules.
- **Rule chung:** Khi có multiple versions, chọn newest by `effective_date` (tie-breaker: latest `exported_at`).

### 4.3 Update Frequency & SLA

| doc_id | Frequency | Lead time (lag tolerance) | Validation | Priority |
|--------|-----------|--------------------------|------------|----------|
| policy_refund_v4 | Daily | 12h | Check "14 ngày" giảm → 0 quarantine_records | **High** |
| hr_leave_policy | Monthly | 48h | Verify effective_date ≥ 2026-01-01 | Medium |
| it_helpdesk_faq | Weekly | 24h | Freshness check: exported_at within 7 days | Medium |
| sla_p1_2026 | Static | 720h (30 ngày) | Manual review; no automation | Low |

---

## 5. Freshness SLA — Dual Boundary Monitoring

> **Sprint 2 — Long:** Đo freshness tại **2 boundary** (ingest + publish) để phát hiện bottleneck giữa các stage.

### 5.1 Boundary Definitions

| Boundary | Measured at | Description | Metric |
|----------|------------|-------------|--------|
| **Ingest** | Sau khi đọc raw CSV | Dữ liệu đã vào pipeline (log: `raw_records`) | `ingest_timestamp` |
| **Publish** | Sau khi upsert ChromaDB | Dữ liệu đã available cho Agent (log: `embed_upsert`) | `publish_timestamp` |

### 5.2 SLA Thresholds

| Level | Condition | Action |
|-------|-----------|--------|
| **PASS** | `age_hours ≤ 24` | ✅ Dữ liệu fresh — pipeline healthy |
| **WARN** | `24 < age_hours ≤ 26` | ⚠️ Sắp vượt SLA — notify team channel |
| **FAIL** | `age_hours > 26` | 🔴 SLA violated — page on-call, create incident |
| **CRITICAL** | `age_hours > 48` | 🚨 Escalate to Lead + rollback to last known good |

### 5.3 Giải thích cho data mẫu

CSV mẫu có `exported_at = 2026-04-10T08:00:00` — **FAIL là hợp lý** vì data đã cũ hơn 24h. Đây là cố ý để dạy:
- SLA áp cho "pipeline run" → cần cập nhật `exported_at` hoặc chỉnh `FRESHNESS_SLA_HOURS` cho phù hợp
- Nhóm ghi giải thích nhất quán trong runbook

---

## 6. Data Lineage

```
Raw CSV (policy_export_dirty.csv)
  │
  ├── [ingest] load_raw_csv() → raw rows (tracked: run_id, raw_records)
  │
  ├── [clean] clean_rows() → cleaned + quarantine
  │     ├── cleaned → artifacts/cleaned/cleaned_<run_id>.csv
  │     └── quarantine → artifacts/quarantine/quarantine_<run_id>.csv
  │
  ├── [validate] run_expectations() → pass/fail/halt decision
  │
  ├── [embed] cmd_embed_internal() → ChromaDB upsert + prune
  │     ├── upsert by chunk_id (idempotent)
  │     └── prune stale vectors (ids not in current cleaned)
  │
  └── [publish] manifest + freshness check
        └── artifacts/manifests/manifest_<run_id>.json
```

**Traceability:** Mỗi run tạo 4 artifacts liên kết bằng `run_id`:
1. `artifacts/logs/run_<run_id>.log` — full pipeline log
2. `artifacts/cleaned/cleaned_<run_id>.csv` — cleaned data
3. `artifacts/quarantine/quarantine_<run_id>.csv` — rejected data + lý do
4. `artifacts/manifests/manifest_<run_id>.json` — summary + freshness
