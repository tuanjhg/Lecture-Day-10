# Runbook — Lab Day 10: Data Pipeline Incident Response

**Tác giả:** Long (Quality & Observability)  
**Cập nhật:** 2026-04-15  
**Áp dụng cho:** `etl_pipeline.py` + ChromaDB collection `day10_kb`  
**Contract tham chiếu:** `contracts/data_contract.yaml` v2.0

---

## Symptom

> Agent trả lời **sai thông tin chính sách** — ví dụ:

| Symptom cụ thể | Ảnh hưởng user | Ưu tiên |
|----------------|---------------|---------|
| Agent nói "**14 ngày** hoàn tiền" thay vì 7 ngày (canonical v4) | Khách hàng hiểu sai quyền lợi → tranh chấp/mất đơn | **P1** |
| Agent nói "**10 ngày phép năm**" thay vì 12 ngày (HR 2026) | Nhân viên bị thiệt quyền lợi → khiếu nại HR | **P1** |
| Agent không tìm thấy thông tin SLA P1 (15 phút phản hồi) | IT Helpdesk xử lý sai priority → vi phạm SLA | **P2** |
| Agent trả lời dựa trên dữ liệu cũ hơn 24h | Thông tin có thể đã thay đổi mà user không biết | **P2** |

---

## Detection

> Các metric và tool phát hiện sự cố:

| Metric / Tool | Câu lệnh kiểm tra | Ngưỡng alert |
|---------------|-------------------|-------------|
| **Freshness SLA** | `python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_<run_id>.json` | FAIL nếu `age_hours > 24 + 2 (grace)` |
| **Expectation suite** | Kiểm tra log: `grep "FAIL" artifacts/logs/run_<run_id>.log` | Bất kỳ expectation `severity=halt` nào FAIL |
| **Eval retrieval** | `python eval_retrieval.py --out artifacts/eval/check.csv` | `hits_forbidden=yes` trên bất kỳ golden question |
| **Quarantine count** | Kiểm tra log: `grep "quarantine_records" artifacts/logs/run_<run_id>.log` | `quarantine_records > 0` cần review |
| **Grading run** | `python grading_run.py --out artifacts/eval/grading_run.jsonl` | `contains_expected=false` hoặc `hits_forbidden=true` |
| **ChromaDB count** | Trong log: `embed_upsert count=N` | Count giảm đột ngột hoặc = 0 |

### Alert escalation (per contract v2.0)

```
Level 1 (WARN):  age_hours > 19.2h (80% of 24h SLA)  →  Notify #data-quality-alerts
Level 2 (FAIL):  age_hours > 24h                       →  Page on-call + create incident
Level 3 (CRIT):  age_hours > 26h (vượt grace period)   →  Escalate to Lead (Dũng) + rollback
```

---

## Diagnosis

> **Timebox:** 0–5' freshness → 5–12' volume/errors → 12–20' schema/lineage → hết time → mitigate trước.

| Bước | Việc làm | Lệnh / File | Kết quả mong đợi |
|------|----------|-------------|-------------------|
| 1 | Kiểm tra manifest gần nhất | `cat artifacts/manifests/manifest_<run_id>.json` | Xem `latest_exported_at`, `run_timestamp`, `raw_records`, `cleaned_records`, `quarantine_records` |
| 2 | Check freshness dual-boundary | `python etl_pipeline.py freshness --manifest <path>` | PASS/WARN/FAIL + `age_hours` tại cả ingest và publish boundary |
| 3 | Đọc pipeline log | `cat artifacts/logs/run_<run_id>.log` | Tìm dòng `FAIL`, `HALT`, `WARN`, `quarantine_records > 0` |
| 4 | Mở quarantine CSV | `cat artifacts/quarantine/quarantine_<run_id>.csv` | Xem `reason` column — xác định loại lỗi: `stale_refund_window_v3`, `unknown_doc_id`, `missing_effective_date`... |
| 5 | Chạy eval retrieval | `python eval_retrieval.py --out artifacts/eval/debug.csv` | So sánh `contains_expected`, `hits_forbidden` — chunk nào đang bị sai? |
| 6 | Kiểm tra ChromaDB trực tiếp | Trong Python: `chromadb.PersistentClient("./chroma_db").get_collection("day10_kb").count()` | Số vector có khớp `cleaned_records` trong manifest không? |
| 7 | So sánh với cleaned CSV | `cat artifacts/cleaned/cleaned_<run_id>.csv` | Cross-check nội dung chunk với canonical docs (`data/docs/*.txt`) |

### Decision tree

```
Agent trả lời sai
  ├── Freshness FAIL?
  │     └── YES → Dữ liệu cũ → Rerun pipeline (goto Mitigation)
  │     └── NO ↓
  ├── Expectation FAIL trong log?
  │     └── YES → Data quality issue → Kiểm tra quarantine + cleaning rules
  │     └── NO ↓
  ├── hits_forbidden = yes trong eval?
  │     └── YES → Stale chunk trong index → Chạy pipeline chuẩn (prune stale)
  │     └── NO ↓
  ├── ChromaDB count ≠ cleaned_records?
  │     └── YES → Embed lỗi → Xóa collection + rerun từ đầu
  │     └── NO ↓
  └── Kiểm tra prompt / model config (không phải lỗi data)
```

---

## Mitigation

> **Nguyên tắc:** Mitigate trước, tìm root cause sau. Rollback không cần biết 100% nguyên nhân.

| Scenario | Action ngay lập tức | Lệnh |
|----------|--------------------|------|
| **Stale refund 14 ngày trong index** | Rerun pipeline chuẩn (fix + prune) | `python etl_pipeline.py run` |
| **Data quá cũ (freshness FAIL)** | Cập nhật raw CSV mới + rerun | Copy CSV mới vào `data/raw/` → `python etl_pipeline.py run` |
| **Expectation halt (data bẩn)** | Không embed — fix cleaning rules trước | Sửa `transform/cleaning_rules.py` → rerun |
| **Unknown source lọt vào** | Pipeline đã quarantine tự động | Verify quarantine CSV → confirm allowlist đúng |
| **ChromaDB corrupt** | Xóa DB + rebuild từ scratch | Xóa `chroma_db/` → `python etl_pipeline.py run` |
| **Tạm thời chưa fix được** | Banner "dữ liệu đang bảo trì" trên UI Agent | Thông báo team + ghi incident log |

### Verify sau mitigation

```bash
# 1. Chạy pipeline chuẩn
python etl_pipeline.py run --run-id fix-<incident-id>

# 2. Verify freshness
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_fix-<incident-id>.json

# 3. Verify retrieval quality
python eval_retrieval.py --out artifacts/eval/after_fix.csv

# 4. Confirm grading pass
python grading_run.py --out artifacts/eval/grading_run.jsonl
```

---

## Prevention

> Sau mỗi sự cố, thêm **ít nhất 1 hành động** vào đây để ngăn tái diễn.

| Sự cố | Prevention đã thêm | Owner |
|-------|-------------------|-------|
| Stale refund 14 ngày từ v3 migration | Cleaning rule quarantine "14 ngày" + Expectation E3 `refund_no_stale_14d_window` (halt) | Hải + Long |
| HR policy version conflict (10 vs 12 ngày) | Filter `effective_date >= 2026-01-01` + Expectation E6 `hr_leave_no_stale_10d_annual` (halt) | Hải + Long |
| BOM/control chars trong CSV export | New rule `no_bom_encoding` (quarantine) + Expectation E7 `no_bom_control_chars` (halt) | Long |
| Future exported_at (clock drift) | New rule `exported_at_not_future` (quarantine) | Long |
| Duplicate vectors sau rerun | Idempotent upsert by stable `chunk_id` + prune stale vectors | Thuận + Dũng |
| SLA freshness bị vượt | Dual-boundary monitoring (ingest + publish) + 3-level alert escalation | Long |
| Unknown source lọt vào allowlist | Strict allowlist trong `data_contract.yaml` + cleaning rule quarantine `unknown_doc_id` | Long + Hải |

### Liên hệ Day 11

- Runbook này là tiền đề cho **guardrails** Day 11 — chuyển prevention rules sang automated guardrails
- Alert escalation có thể tích hợp vào monitoring stack (Prometheus/Grafana nếu scale)
- Data contract v2.0 có thể mở rộng thành policy-as-code cho toàn hệ thống
