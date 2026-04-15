# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Hồ Hải Thuận  
**Vai trò:** Vector DB Specialist (ChromaDB, Idempotency & Pruning)  
**Ngày nộp:** 2026-04-15  
**Độ dài yêu cầu:** **400–650 từ**

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `vector_store/chroma_store.py`: Xây dựng toàn bộ logic kết nối, upsert dữ liệu và cơ chế pruning cho ChromaDB.
- `.env`: Thiết lập các biến môi trường cấu hình DB (`CHROMA_DB_PATH`, `CHROMA_COLLECTION`) để đảm bảo tính linh hoạt khi triển khai.

**Kết nối với thành viên khác:**
Nhận dữ liệu đã được làm sạch từ **Transformation** (Tuấn, Quang) thông qua hàm `clean_rows`. Sau đó, cung cấp các chỉ số đo lường (metrics) về việc nạp dữ liệu cho **Dũng (Lead)** để ghi log và cho **Huy (Eval)** để thực hiện đánh giá chất lượng truy xuất sau khi nạp.

**Bằng chứng (commit / comment trong code):**
Tôi đã thực hiện các thay đổi quan trọng trong `chroma_store.py` để chuyển đổi cơ chế định danh từ `chunk_id` đơn thuần sang `content_hash` để đảm bảo tính nhất quán (idempotency).

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Một trong những quyết định kỹ thuật quan trọng nhất mà tôi thực hiện là chọn chiến lược **Idempotency dựa trên Content Hashing**. Thay vì tin tưởng hoàn toàn vào `chunk_id` từ nguồn cấp (vốn có thể bị trùng hoặc thay đổi tùy tiện), tôi đã viết hàm `_row_content_hash` để tạo ra mã định danh duy nhất dựa trên nội dung thực tế (`doc_id` + `effective_date` + `chunk_text`). 

Quyết định này giúp hệ thống đạt được trạng thái lý tưởng: chạy lại pipeline n lần với cùng một tập dữ liệu thì số lượng vector trong ChromaDB vẫn không thay đổi (`embed_duplicate_ratio_pct = 0.0`). Điều này cực kỳ quan trọng trong môi trường production nơi pipeline có thể bị lỗi giữa chừng và cần chạy lại mà không làm "rác" cơ sở dữ liệu vector hoặc làm sai lệch kết quả truy xuất top-k.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

Trong quá trình triển khai Sprint 3, tôi đã gặp phải lỗi **`UnicodeEncodeError`** khi chạy pipeline trên môi trường Windows. Hệ thống crash khi cố gắn in ra ký tự mũi tên `→` trong các dòng log thông báo kết quả. Tôi đã xử lý bằng cách chuẩn hóa lại các chuỗi log, thay thế các ký tự unicode phức tạp bằng ký tự ASCII chuẩn (`->`), giúp pipeline chạy mượt mà trên mọi console.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Dưới đây là bằng chứng kết quả từ log thực tế của lần chạy thành công nhất:

**Run ID:** `2026-04-15T09-32Z`
- **Trước khi chạy (Collection count before):** `0` (DB trống)
- **Sau khi chạy (Collection count after):** `6`
- **Số lượng Upsert thành công:** `6`
- **Tỷ lệ trùng lặp (Duplicate ratio):** `0.0%`

Dữ liệu đã được nạp thành công vào collection `day10_kb`, sẵn sàng cho bước Evaluation của Huy.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ triển khai tính năng **Semantic Deduplication**. Hiện tại hệ thống chỉ chống trùng lặp dựa trên text chính xác 100%. Tôi muốn tích hợp một bước kiểm tra độ tương đồng (cosine similarity) để phát hiện các đoạn text gần giống nhau (chỉ khác dấu câu hoặc khoảng trắng) và chỉ giữ lại bản ghi có metadata (ngày hiệu lực) mới nhất, giúp tối ưu không gian lưu trữ và độ chính xác khi tìm kiếm.
