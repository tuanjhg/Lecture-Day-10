# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Quách Ngọc Quang  
**Mã HV:** 2A202600285  
**Vai trò:** Transformation / Adversarial Stress Testing  
**Ngày nộp:** 2026-04-15  

---

## 1. Tôi phụ trách phần nào?

**Nhiệm vụ:** Trong Sprint 3, tôi phụ trách tạo kịch bản "Inject Corruption" cực khó để đánh giá sức chịu đựng của Data Pipeline (Stress Test), chứng minh hệ thống hoạt động chính xác trước các dữ liệu đầu vào độc hại hoặc phi tiêu chuẩn. (Công việc phụ trách Sprint 1 tạo dữ liệu thô ban đầu đã được loại trừ khỏi báo cáo này theo yêu cầu).

**File / module:**
- `data/raw/policy_stress_test.csv`: Chứa 10 kịch bản dữ liệu nâng cao (BOM, nhiễu emoji, mâu thuẫn thời gian, phá tokenizer...).
- `docs/stress_test_analysis.md`: Tài liệu phân tích và thiết kế chiến lược kịch bản kiểm thử "Data Firewall".

**Kết nối với thành viên khác:**
Tôi làm việc trực tiếp với Tuấn (Transformation) để thảo luận các kịch bản lỗi, từ đó cung cấp tài liệu cho Long và Hải (Quality) viết các rule/expectation ngăn chặn ngay tại pipeline.

**Bằng chứng:** 
- Tài liệu `docs/stress_test_analysis.md` với bảng kịch bản đối kháng (Adversarial Scenarios) chi tiết được ánh xạ từ `st_adv_01` tới `st_adv_10`.
- File CSV `policy_stress_test.csv` mô phỏng các lỗi gõ sai logic, spam whitespace và control chars.

---

## 2. Một quyết định kỹ thuật

**Chiến lược xử lý lỗi nhiễu Tokenizer (Whitespace/Control Characters):**
Khi thiết kế bộ test `st_adv_04` chứa rất nhiều Tabs, Newlines và Zero-width spaces, tôi phải quyết định nên đề xuất chặn bỏ (Halt/Quarantine) hay làm sạch (Clean/Normalize). 

Quyết định: Tôi thống nhất với nhóm là **không được loại bỏ (Drop)** toàn bộ chunk này vì phần text chứa chính sách (ví dụ SLA P1 4 giờ) vẫn rất có giá trị với người dùng. Thay vào đó, thiết kế pipeline cần chạy qua rule `no_excessive_whitespace` (báo warn) để tự động làm sạch và gom cụm ("collapse") các khoảng trắng thừa trước khi nạp vào ChromaDB, giúp bảo toàn được logic nghiệp vụ cốt lõi mà không làm sai lệch distance vector. Cùng lúc đó, các control-chars dạng hex code sẽ bị chặn đứt điểm tại E7 `no_bom_control_chars` để tránh lỗi engine.

---

## 3. Một lỗi hoặc anomaly đã xử lý

**Triệu chứng:** Trong quá trình thử nghiệm tiêm dữ liệu cực đoan, các đoạn văn bản có xen kẽ nhiều khoảng trắng bất hợp lý hoặc dính lỗi Encoding BOM khiến Vector DB (ChromaDB) hoạt động thiếu tối ưu, chất lượng retrieval bị tụt vì text đầu vào bị nhận dạng khác biệt so với text của câu hỏi (dù semantic giống nhau).

**Phát hiện và Fix:** Thông qua kịch bản mã `st_adv_04`, tôi phát hiện việc Tokenizer bị cắt vụn một cách vô nghĩa. Nhóm đã dựa vào đó để triển khai hàm `_normalize_whitespace` bên trong `transform/cleaning_rules.py`. Kết quả là metric `cleaned_excessive_whitespace_fixed` đã có thể đo đếm được sự cải thiện này lúc runtime.

---

## 4. Bằng chứng trước / sau

Tôi đã setup kịch bản `--run-id adv-stress` để nhóm có mẫu đối chiếu:

* **Trước (Inject bad):** Chạy lệnh bằng data lỗi `python etl_pipeline.py run --raw data/raw/policy_stress_test.csv --no-refund-fix --skip-validate`. Các rule bị bypass, dữ liệu rác (BOM) lọt vào Vector DB. 
* **Sau (Expectation bảo vệ):** Chạy pipeline với Expectation được bật, kịch bản của tôi ngay lập tức làm pipeline báo `halt` nhờ Expectation mới:
  `ExpectationResult(name='no_bom_control_chars', passed=False, severity='halt')`
  Đồng thời metric `quarantine_future_exported_at` thu gom được trường hợp spam thời gian (dòng st_adv_10).

---

## 5. Cải tiến tiếp theo

Nếu có thêm 2 giờ làm việc, tôi sẽ trực tiếp code thêm cleaning rule `mask_pii` (dùng Regex để redaction SĐT và Email thành chữ `[REDACTED]`) để giải quyết trọn vẹn kịch bản `st_adv_03`, giúp đảm bảo tính tuân thủ tuyệt đối về Data Privacy.
