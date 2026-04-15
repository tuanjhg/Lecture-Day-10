# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Khổng Mạnh Tuấn  
**Vai trò:** Cleaning / Data Quality  
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** **400–650 từ** (ngắn hơn Day 09 vì rubric slide cá nhân ~10% — vẫn phải đủ bằng chứng)

---

> Viết **"tôi"**, đính kèm **run_id**, **tên file**, **đoạn log** hoặc **dòng CSV** thật.  
> Nếu làm phần clean/expectation: nêu **một số liệu thay đổi** (vd `quarantine_records`, `hits_forbidden`, `top1_doc_expected`) khớp bảng `metric_impact` của nhóm.  
> Lưu: `reports/individual/[ten_ban].md`

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `transform/cleaning_rules.py` — toàn bộ module xử lý validation, dedup, và quality enforcement
- `contracts/data_contract.yaml` — schema definition, quality rules severity, freshness SLA
- `docs/data_contract.md` — documentation mô tả version resolution strategy và quarantine rules

**Kết nối với thành viên khác:**

Tôi xây dựng cleaning layer đầu tiên — raw CSV từ ingestion đi qua cleaning_rules, được deduplicated và quarantine các records lỗi, rồi output sang cleaned CSV. Phía sau, embedding team sử dụng cleaned data để vector hóa chunk_text. Monitoring team dùng metric `quarantine_records` và `dedup_count` từ CleaningMetrics để alert nếu quality threshold vượt.

**Bằng chứng (commit / comment trong code):**

Module docstring (dòng 1–8 trong cleaning_rules.py) ghi rõ scope: schema validation, quality rules, version resolution, freshness. Class `CleaningMetrics` (dòng ~150) track impact của từng rule.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

**Quyết định: Halt vs Warn — severity của "stale refund window" rule**

Tôi quyết định set severity = "halt" cho rule `no_stale_refund_window` (chứa "14 ngày" thay vì canonical "7 ngày") vì đây là migration risk từ v3 → v4 có thể dẫn đến legal/compliance issue nếu customer nhận refund window sai. Nếu chỉ "warn", pipeline vẫn chạy và chunks lỗi vô vector store, mất control. "Halt" buộc Data Owner phải explicitly approve hoặc fix trước publish. Các rule khác như duplicate_chunk_id chỉ cần "warn" và auto-drop latest, vì điều này có thể xảy ra hợp lệ trong reprocessing.

**Bằng chứng:** `contracts/data_contract.yaml` dòng ~27–30 ghi `severity: "halt"` cho rule này, và cleaning_rules.py (~dòng 180) check flag này để raise exception nếu apply_refund_window_fix=True.

---

**Lỗi: Date format inconsistency — effective_date "DD/MM/YYYY" vs ISO 8601**

**Triệu chứng:** Test data từ IT Helpdesk export (`it_helpdesk_faq.txt`) chứa `effective_date="01/02/2026"` (DD/MM/YYYY format). Khi cleaning_rules.py cố parse này, datetime validation fail vì code chỉ expect ISO 8601 (YYYY-MM-DD), dẫn tới record bị QUARANTINE thay vì cleaned.

**Phát hiện & Fix:** Tôi thêm function `_normalize_effective_date()` (dòng ~70–95 trong cleaning_rules.py) dùng regex `_DMY_SLASH` để detect và convert DD/MM/YYYY → YYYY-MM-DD. Nếu format invalid (không match cả ISO lẫn DD/MM/YYYY), record vẫn QUARANTINE nhưng log clear reason = "invalid_effective_date_format" để debugging. Giải pháp này tự động hóa được, không cần manual intervention từ Data Owner nữa.

**Metric impact:** `invalid_date_format` quarantine count giảm từ ~8 records → 0 trong run_id "ci-smoke2".ng → metric/check nào phát hiện → fix.

_________________

