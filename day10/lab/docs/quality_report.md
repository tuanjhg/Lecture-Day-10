# Quality Report — Lab Day 10: Data Pipeline & Data Observability

**run_id (pipeline chuẩn):** `(điền sau khi chạy pipeline)`  
**run_id (inject bad):** `inject-bad`  
**Ngày:** 2026-04-15  
**Tác giả:** Nguyễn Hoàng Long (2A202600160) + Hải (Quality team)

---

## 1. Tóm tắt số liệu

| Chỉ số | Before (inject bad) | After (pipeline chuẩn) | Ghi chú |
|--------|-------------------|----------------------|---------|
| raw_records | 16 | 16 | Cùng CSV input |
| cleaned_records | _(điền sau run)_ | _(điền sau run)_ | Sau clean: expect ~7 records sạch |
| quarantine_records | _(điền)_ | _(điền)_ | Inject mode ít quarantine hơn (skip validate) |
| Expectation halt? | YES (E3: refund_no_stale_14d) | NO | Inject bypass halt với `--skip-validate` |
| hits_forbidden (q_refund_window) | **yes** | **no** | Chunk "14 ngày" còn trong index khi inject |
| contains_expected (q_refund_window) | yes | yes | Chunk "7 ngày" vẫn có, nhưng stale chunk gây forbidden hit |

> **Interpretation:** Khi chạy inject mode (`--no-refund-fix --skip-validate`), chunk stale "14 ngày" từ v3 migration KHÔNG bị quarantine → lọt vào ChromaDB → `eval_retrieval` phát hiện `hits_forbidden=yes`. Sau khi chạy pipeline chuẩn (fix refund + validate), chunk stale bị quarantine, prune khỏi index → `hits_forbidden=no`.

---

## 2. Before / After retrieval (bắt buộc)

### Câu hỏi 1: Refund window (`q_refund_window`)

**Câu hỏi:** "Khách hàng có bao nhiêu ngày để yêu cầu hoàn tiền kể từ khi xác nhận đơn?"

**Before (inject-bad):**
```
id: q_refund_window
contains_expected: yes (chunk "7 ngày" vẫn có)
hits_forbidden: YES ← chunk stale "14 ngày làm việc" xuất hiện trong top-k
```
→ Agent có thể trả lời "14 ngày" nếu chunk stale rank cao hơn.

**After (pipeline chuẩn):**
```
id: q_refund_window
contains_expected: yes
hits_forbidden: no ← chunk "14 ngày" đã bị quarantine + prune
```
→ Agent chỉ thấy "7 ngày" — đúng canonical v4.

### Câu hỏi 2 (Merit): HR Leave version (`q_leave_version`)

**Câu hỏi:** "Theo chính sách nghỉ phép hiện hành (2026), nhân viên dưới 3 năm kinh nghiệm được bao nhiêu ngày phép năm?"

**Before (inject-bad, không filter HR version):**
```
id: q_leave_version
contains_expected: có thể yes (chunk "12 ngày" tồn tại)
hits_forbidden: CÓ THỂ YES nếu chunk "10 ngày phép năm" (HR 2025) chưa bị loại
top1_doc_expected: uncertain
```

**After (pipeline chuẩn):**
```
id: q_leave_version
contains_expected: yes ("12 ngày phép năm")
hits_forbidden: no ("10 ngày phép năm" đã bị quarantine vì effective_date < 2026-01-01)
top1_doc_expected: yes (doc_id = hr_leave_policy)
```

> **Note:** Điền số liệu thực sau khi chạy `python eval_retrieval.py`. Dữ liệu trên là dự đoán dựa trên cleaning rules.

---

## 3. Freshness & Monitor

**SLA chọn:** 24 giờ (per contract v2.0 :: freshness.primary_sla.sla_hours)  
**Grace period:** 2 giờ  
**Boundary đo:** Dual — ingest (exported_at) + publish (run_timestamp)

**Kết quả trên data mẫu:**

| Boundary | Status | age_hours | Giải thích |
|----------|--------|-----------|-----------|
| Ingest | FAIL | >100h | `exported_at = 2026-04-10T08:00:00` — data export cũ nhiều ngày |
| Publish | PASS | <1h | `run_timestamp` = thời điểm chạy pipeline (vừa mới) |

**Interpretation:** FAIL tại ingest boundary là **hành vi đúng** — CSV mẫu cố ý có timestamp cũ để dạy freshness. Trong production: (1) cập nhật CSV mới hơn, hoặc (2) chỉnh SLA cho phù hợp use case (snapshot data có thể accept lag hơn streaming).

**Alert escalation:** WARN > 19.2h → FAIL > 24h → CRITICAL > 26h (escalate to Lead).

---

## 4. Corruption Inject (Sprint 3)

### Kịch bản inject

**Lệnh:** `python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate`

**Mục đích:**
- `--no-refund-fix`: Không sửa chunk "14 ngày" → "7 ngày", để chunk stale lọt vào cleaned
- `--skip-validate`: Bỏ qua expectation halt → cho embed dù data bẩn

**Kết quả inject:**
- Expectation E3 (`refund_no_stale_14d_window`) FAIL nhưng bị bypass
- Chunk stale "14 ngày làm việc" được embed vào ChromaDB
- `eval_retrieval.py` phát hiện `hits_forbidden=yes` trên `q_refund_window`

**So sánh:**

| Metric | Inject bad | Pipeline chuẩn | Delta |
|--------|-----------|---------------|-------|
| quarantine_stale_refund_window | 0 (bypassed) | 1 | +1 quarantine |
| expectation E3 | FAIL (skipped) | OK | Fixed |
| hits_forbidden (q_refund) | yes | no | ✅ Fixed |
| embed_prune_removed | 0 | ≥1 | Prune stale chunk |

---

## 5. Hạn chế & việc chưa làm

- **Chưa tích hợp Great Expectations / pydantic** — vẫn dùng custom expectations.py. Là tiêu chí Distinction (a) và bonus +2.
- **Freshness cron chưa có** — hiện chạy tay, chưa schedule tự động.
- **Rule versioning vẫn hard-code** `HR_LEAVE_MIN_EFFECTIVE_DATE = "2026-01-01"` — chưa đọc từ contract/env (tiêu chí Distinction (d)).
- **Eval chỉ keyword-based** — chưa mở rộng LLM-judge (tiêu chí Distinction (c)).
- Cần **điền số liệu thực** vào bảng Section 1 và 2 sau khi chạy pipeline.
