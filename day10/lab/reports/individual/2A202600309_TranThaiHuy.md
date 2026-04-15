# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** TranThaiHuy  
**Mã học viên:** 2A202600309  
**Vai trò:** Evaluation Lead (Evidence & Retrieval Eval)  
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** 400–650 từ

---

## 1. Tôi phụ trách phần nào? (≈110 từ)

Tôi phụ trách phần **đánh giá (evaluation) và bằng chứng (evidence)** để chứng minh pipeline Day 10 ảnh hưởng trực tiếp đến retrieval/agent ở tầng trên. Công việc của tôi là chạy pipeline theo 2 kịch bản (clean vs inject-bad), sinh ra artifacts liên quan (log/manifest/eval CSV), và dùng các chỉ số `contains_expected`, `hits_forbidden`, `top1_doc_expected` để kết luận “trước/sau” một cách định lượng.

**File tôi trực tiếp sử dụng/đối chiếu:**
- `eval_retrieval.py` + `data/test_questions.json` để chạy retrieval eval.
- Artifacts theo run: `artifacts/logs/run_good.log`, `artifacts/logs/run_inject-bad.log`, `artifacts/manifests/manifest_good.json`, `artifacts/manifests/manifest_inject-bad.json`.
- Output eval: `artifacts/eval/before_after_eval.csv`, `artifacts/eval/after_inject_bad.csv`.

---

## 2. Một quyết định kỹ thuật (≈140 từ)

Quyết định quan trọng là **tách rõ 2 mode chạy** để phục vụ đúng mục tiêu Sprint 2 và Sprint 3:

- **Pipeline chuẩn (Sprint 2)**: phải tạo index “canonical” để agent không đọc policy stale. Vì vậy dữ liệu refund “14 ngày” cần được **auto-fix về 7 ngày** trước khi embed, expectation `refund_no_stale_14d_window` phải PASS, và ChromaDB nhận snapshot sạch.
- **Inject-bad (Sprint 3)**: cần cố ý giữ lỗi để tạo before/after measurable. Do đó dùng `--no-refund-fix --skip-validate` để expectation E3 FAIL nhưng vẫn embed “dirty index”, từ đó eval nhìn thấy `hits_forbidden=yes` và chứng minh nguy cơ “mồi cũ” trong top-k.

Trade-off: phức tạp hơn so với chỉ “halt luôn”, nhưng phù hợp lab vì vừa chạy được pipeline chuẩn, vừa có kịch bản demo lỗi.

---

## 3. Một lỗi/anomaly đã xử lý (≈120 từ)

Anomaly tôi gặp là pipeline có thể bị **HALT** khi phát hiện stale refund window (“14 ngày”) nếu logic fix/validation không được tách rõ theo mode. Khi đó Sprint 2 không đi tới embed nên không thể chạy eval.

Tôi kiểm tra bằng cách đọc log và metrics:
- `metric[stale_refund_window_detected]=1` (phát hiện chunk stale)
- Ở inject-bad, expectation E3 FAIL nhưng có `--skip-validate` để tiếp tục embed.

Sau khi điều chỉnh cách chạy theo đúng mode (good vs inject-bad), pipeline chuẩn (`run_id=good`) có `expectation[refund_no_stale_14d_window] OK ... violations=0` và `embed_upsert count=7`, đảm bảo eval có thể chạy.

---

## 4. Bằng chứng trước / sau (≈110 từ)

**Before (inject-bad)** — `run_id=inject-bad`:
- Log: `expectation[refund_no_stale_14d_window] FAIL (halt) :: violations=1` và `--skip-validate` để vẫn embed.
- Eval CSV `artifacts/eval/after_inject_bad.csv`: `q_refund_window` có `contains_expected=yes` nhưng `hits_forbidden=yes` (top-k vẫn dính “14 ngày”).

**After (pipeline chuẩn)** — `run_id=good`:
- Log: `metric[cleaned_refund_window_fixed]=1`, expectation E3 OK, `embed_upsert count=7`.
- Eval CSV `artifacts/eval/before_after_eval.csv`: `q_refund_window` có `contains_expected=yes` và `hits_forbidden=no` (index sạch hơn).

Ý nghĩa: inject-bad chứng minh “data lỗi” làm retrieval kéo nhầm chunk stale; pipeline chuẩn loại/fix nên retrieval sạch.

---

## 5. Cải tiến tiếp theo (≈60 từ)

Nếu có thêm 2 giờ, tôi sẽ mở rộng eval theo 2 hướng: (1) thêm cột `scenario` để gộp before/after vào một CSV duy nhất, thuận tiện đọc và chấm; (2) tăng bộ câu hỏi (≥5) theo slice (refund/HR/IT/SLA) để tránh phụ thuộc 1 câu then chốt và có cái nhìn ổn định hơn về chất lượng retrieval.
