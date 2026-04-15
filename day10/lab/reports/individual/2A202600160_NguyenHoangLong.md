# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Hoàng Long  
**Mã học viên:** 2A202600160  
**Vai trò:** Quality & Observability Owner
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** **400–650 từ**

---

## 1. Tôi phụ trách phần nào? (≈110 từ)

**File / module:**

- `contracts/data_contract.yaml` — nâng cấp từ v1.0 → v2.0: thêm contract metadata, ownership 7 thành viên, 3 quality rules mới, dual-boundary freshness SLA, data lineage, monitoring config, governance workflow.
- `docs/data_contract.md` — đồng bộ hoàn toàn với YAML v2.0, mở rộng source map 6 nguồn, bảng quarantine 11 rules.
- `docs/pipeline_architecture.md` — vẽ sơ đồ Mermaid flowchart 5 stages, bảng ranh giới trách nhiệm, mô tả idempotency.
- `monitoring/freshness_check.py` — mở rộng từ single-boundary sang dual-boundary (ingest + publish), thêm WARN level, per-source SLA check.
- `docs/runbook.md` — viết đầy đủ 5 mục Symptom→Detection→Diagnosis→Mitigation→Prevention.
- `transform/cleaning_rules.py` — thêm 3 rules mới: `no_bom_encoding`, `no_excessive_whitespace`, `exported_at_not_future`.
- `quality/expectations.py` — thêm 2 expectations: E7 `no_bom_control_chars` (halt), E8 `cleaned_ratio_above_50pct` (warn).

**Kết nối với thành viên khác:**

Tôi thuộc sub-team Quality cùng Hải. Tôi cung cấp contract (SLA, rules) và monitoring cho Dũng (Lead) tích hợp vào pipeline. Hải viết expectations.py baseline, tôi mở rộng thêm E7/E8 và đảm bảo sync giữa contract YAML ↔ cleaning rules ↔ expectations.

---

## 2. Một quyết định kỹ thuật (≈140 từ)

> **Quyết định:** Đo freshness tại **2 boundary** (ingest + publish) thay vì chỉ 1.

Baseline ban đầu `freshness_check.py` chỉ đo `latest_exported_at` — tức chỉ biết data được export từ source khi nào, nhưng không biết data đã **thực sự publish lên ChromaDB** chưa. Trong thực tế, pipeline có thể ingest thành công (freshness PASS) nhưng embed thất bại → agent vẫn đọc data cũ mà monitoring không báo.

Tôi quyết định thêm `publish_boundary` đo `run_timestamp` (thời điểm pipeline kết thúc embed). Hàm `check_dual_boundary_freshness()` trả về status cho cả 2 boundary + `pipeline_latency_minutes` (khoảng cách giữa ingest và publish). Nếu latency cao → bottleneck ở stage clean/validate/embed.

Thêm 3-level alert (WARN khi >80% SLA, FAIL khi vượt, CRITICAL khi vượt cả grace 2h) theo mô hình SRE error budget — tránh binary pass/fail không có cảnh báo sớm.

Trade-off: phức tạp hơn single-boundary, nhưng phát hiện được class lỗi mà single-boundary bỏ sót.

---

## 3. Một lỗi hoặc anomaly đã xử lý (≈130 từ)

> **Anomaly:** Freshness check **FAIL** trên data mẫu ngay lần chạy đầu tiên.

**Triệu chứng:** Khi chạy `python etl_pipeline.py run`, log báo `freshness_check=FAIL` dù pipeline exit 0 thành công. Toàn bộ records được cleaned và embed đúng, nhưng freshness báo đỏ.

**Metric phát hiện:** `age_hours` trong manifest rất cao (>100h) vì `exported_at` trong CSV mẫu là `2026-04-10T08:00:00` — data được "export" từ nhiều ngày trước.

**Phân tích:** Đây là **cố ý trong lab** — CSV mẫu mô phỏng tình huống sync cũ. `FRESHNESS_SLA_HOURS=24` trong `.env` nghĩa là data phải được refresh trong 24h, nhưng data mẫu cũ hơn rất nhiều.

**Xử lý:** Ghi rõ trong runbook Section "Giải thích cho data mẫu": FAIL là **hành vi đúng**, chứng minh freshness check hoạt động. Nhóm có 2 lựa chọn: (1) chỉnh `FRESHNESS_SLA_HOURS` cho phù hợp demo, hoặc (2) cập nhật timestamp mới trong CSV. Cả hai đều hợp lệ nếu giải thích nhất quán.

---

## 4. Bằng chứng trước / sau (≈100 từ)

> **Scenario:** Inject corruption (Sprint 3) — chạy pipeline với `--no-refund-fix --skip-validate` vs pipeline chuẩn.

**Before (inject bad — không fix refund, bỏ qua validation):**
```
run_id=inject-bad
expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1
WARN: expectation failed but --skip-validate → tiếp tục embed
freshness_check=FAIL
```
→ Eval: `q_refund_window`: `hits_forbidden=yes` (chunk "14 ngày" còn trong top-k)

**After (pipeline chuẩn — fix refund + validation pass):**
```
run_id=fix-clean
expectation[refund_no_stale_14d_window] OK (halt) :: violations=0
embed_prune_removed=1  ← xóa chunk stale
freshness_check=FAIL  (do exported_at cũ — expected)
PIPELINE_OK
```
→ Eval: `q_refund_window`: `contains_expected=yes`, `hits_forbidden=no` ✅

---

## 5. Cải tiến tiếp theo (≈60 từ)

Nếu có thêm 2 giờ, tôi sẽ **tích hợp Great Expectations** (pydantic model) thay cho custom expectations.py hiện tại — đây là tiêu chí Distinction (+2 bonus). Cụ thể: define `DataContractSchema` bằng pydantic `BaseModel` validate mỗi row cleaned, tự động sinh report HTML với GE. Đồng thời thêm **scheduled freshness cron** chạy mỗi giờ đọc manifest mới nhất và gửi alert tự động thay vì chạy tay.
