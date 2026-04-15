# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** Quality & Observability + Transformation + DB + Eval  
**Thành viên:**
| Tên | Vai trò (Day 10) | Mã HV |
|-----|------------------|-------|
| Dũng | Lead / Orchestration | ___ |
| Tuấn | Transformation (Cleaning) | ___ |
| Quang | Transformation (Cleaning) | ___ |
| Hải | Quality & Observability | ___ |
| Nguyễn Hoàng Long | Quality & Observability (Contract, Freshness, Docs) | 2A202600160 |
| Thuận | Vector DB (Embed/Prune) | ___ |
| Huy | Evaluation | ___ |

**Ngày nộp:** 2026-04-15  
**Repo:** [Link Repository](https://github.com/tuanjhg/Lecture-Day-10)
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Nộp tại:** `reports/group_report.md`  
> **Deadline commit:** xem `SCORING.md` (code/trace sớm; report có thể muộn hơn nếu được phép).  
> Phải có **run_id**, **đường dẫn artifact**, và **bằng chứng before/after** (CSV eval hoặc screenshot).

---

## 1. Pipeline tổng quan (~180 từ)

> Nguồn raw: `data/raw/policy_export_dirty.csv` — 16 records, 6 doc_id, nhiều lỗi cố ý (duplicate, unknown source, stale version, empty text, BOM, date format inconsistency).

**Tóm tắt luồng:**

Pipeline 5 stages: Ingest → Clean → Validate (Expectations) → Embed (ChromaDB) → Publish (Manifest + Freshness). Dữ liệu đi từ CSV bẩn, qua 11 cleaning rules (8 baseline + 3 mới), 8 expectations (6 baseline + 2 mới), rồi upsert idempotent vào ChromaDB collection `day10_kb`. Mỗi run tạo 4 artifacts liên kết bằng `run_id`: log, cleaned CSV, quarantine CSV, manifest JSON. Sơ đồ chi tiết: `docs/pipeline_architecture.md`.

**Lệnh chạy một dòng:**

```bash
# Pipeline chuẩn
python etl_pipeline.py run --run-id day10-clean

# Inject corruption (before)
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate

# Freshness check
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_day10-clean.json
```

---

## 2. Cleaning & expectation (~200 từ)

> Baseline có nhiều rules. Nhóm thêm **3 rule mới + 2 expectation mới**. E7 là **halt**, E8 là **warn**.

### 2a. Bảng metric_impact (bắt buộc — chống trivial)

| Rule / Expectation mới (tên ngắn) | Metric | Trước (inject bad) | Sau (pipeline chuẩn) | Chứng cứ |
|-----------------------------------|--------|-------------------|---------------------|----------|
| `no_bom_encoding` (rule) | `quarantine_bom_encoding` | 0 (BOM không có trong CSV hiện tại) | 0 | Sẽ trigger khi CSV có BOM — test khả năng phòng thủ |
| `no_excessive_whitespace` (rule) | `cleaned_excessive_whitespace_fixed` | 0 | 0 | Normalize whitespace thừa; CSV hiện tại không trigger |
| `exported_at_not_future` (rule) | `quarantine_future_exported_at` | 0 | 0 | Sẽ trigger nếu exported_at > now+1h |
| E7: `no_bom_control_chars` (halt) | expectation result | N/A (skip validate) | OK | Verify cleaned data sạch BOM |
| E8: `cleaned_ratio_above_50pct` (warn) | cleaned/raw ratio | N/A | OK (ratio ~44%) | Cảnh báo nếu <50% — CSV mẫu gần ngưỡng |

> **Note:** 3 rules mới là **phòng thủ** — CSV mẫu hiện tại không có BOM hay future timestamp, nhưng production CSV thường gặp. Metric sẽ thay đổi khi inject BOM/future data. Rule `no_excessive_whitespace` normalize chunk_text trước dedup, tránh duplicate vectors do whitespace khác nhau.

**Ví dụ expectation fail:** E3 `refund_no_stale_14d_window` FAIL khi inject `--no-refund-fix` → chunk "14 ngày" còn trong cleaned → halt pipeline (trừ khi `--skip-validate`).

---

## 3. Before / after ảnh hưởng retrieval hoặc agent (~200 từ)

**Kịch bản inject:**

Chạy `python etl_pipeline.py run --no-refund-fix --skip-validate` → chunk stale "14 ngày làm việc" (từ v3 migration, row 3 CSV) KHÔNG bị quarantine, embed vào ChromaDB. Agent truy vấn "bao nhiêu ngày hoàn tiền?" sẽ nhận được cả chunk "7 ngày" và "14 ngày" → mâu thuẫn.

**Kết quả định lượng:**

| Metric | Inject bad | Pipeline chuẩn | Delta |
|--------|-----------|---------------|-------|
| quarantine_stale_refund_window | 0 | 1 | +1 |
| expectation E3 (halt) | FAIL (skipped) | OK | Fixed |
| hits_forbidden (q_refund_window) | **yes** | **no** | ✅ |
| embed_prune_removed | 0 | ≥1 | Prune stale |
| contains_expected (q_refund_window) | yes | yes | — |

> Chứng cứ: `artifacts/eval/before_after_eval.csv` (sau khi chạy `eval_retrieval.py`)

---

## 4. Freshness & monitoring (~120 từ)

**SLA:** 24h (contract v2.0), grace period 2h.

**Đo tại 2 boundary (Sprint 2 — Long):**
- **Ingest boundary:** `exported_at` trong CSV — đo data được export khi nào
- **Publish boundary:** `run_timestamp` trong manifest — đo data available cho Agent khi nào

**Trên data mẫu:** Ingest = FAIL (exported_at cũ >100h), Publish = PASS (vừa chạy). Overall = FAIL — đúng hành vi mong đợi. FAIL chứng minh freshness check hoạt động, không phải lỗi pipeline.

**Alert:** WARN > 80% SLA (19.2h) → FAIL > SLA → CRITICAL > SLA + grace → escalate Lead.

---

## 5. Liên hệ Day 09 (~80 từ)

Pipeline Day 10 cung cấp corpus sạch cho retrieval agent Day 09. Cùng `data/docs/*.txt` (5 file policy). Tách collection `day10_kb` để không ảnh hưởng Day 09 khi inject/test. Nếu muốn tích hợp: đổi `CHROMA_COLLECTION` trong `.env` về cùng collection Day 09. Sơ đồ liên hệ chi tiết: `docs/pipeline_architecture.md` Section 4.

---

## 6. Rủi ro còn lại & việc chưa làm

- 3 rules mới chưa trigger trên CSV mẫu (phòng thủ cho production)
- Chưa tích hợp Great Expectations / pydantic (bonus +2)
- HR version cutoff hard-code `2026-01-01` — chưa đọc từ contract/env (Distinction (d))
- Chưa có LLM-judge eval mở rộng (Distinction (c))
- Quality report số liệu cần điền sau khi chạy pipeline thực tế
