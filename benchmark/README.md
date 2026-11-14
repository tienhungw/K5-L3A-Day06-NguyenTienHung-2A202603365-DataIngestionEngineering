# Benchmark

File câu hỏi: `questions.jsonl` (25 câu: 18 dev, 7 test). Kiểm chứng bằng `python -m src.run check-benchmark`, kết quả ở `results/benchmark_check.json`.

## Trường dữ liệu

`id`, `split`, `type`, `question`, `expected_answer`, `gold_source_id`, `gold_page`, `evidence_quote`, `filter`, và `alt_gold` (các nguồn hợp lệ khác, nếu có).

- `gold_page` là **số Điều** trong văn bản, vì corpus không phân trang (xem `data/manifest.json`).
- `alt_gold` được dùng khi câu hỏi không nêu phiên bản luật và cả bản 2012 lẫn 2019 đều trả lời được. Trúng bất kỳ nguồn nào trong `gold_source_id`/`alt_gold` đều tính là hit.
- `type`: `truc_tiep` (6 câu), `dien_dat_lai` (6), `dieu_kien` (7), `metadata` (6, các câu có filter).

## Chia dev/test

Chia theo chủ đề (Chương), chốt trước khi chạy truy xuất:

- **test**: Chương VIII (kỷ luật lao động), X (lao động nữ), XI (lao động chưa thành niên, cao tuổi): q19–q25.
- **dev**: các Chương còn lại (I, II, III, VI, VII, XII): q01–q18.

Nguy cơ rò rỉ: hai bộ luật có nhiều đoạn gần giống nhau, và dev/test cùng một kiểu câu hỏi. Chia theo Chương giúp không có Điều nào vừa là gold của dev vừa là gold của test, nhưng phong cách câu hỏi vẫn giống nhau.

## Filter

Có 6 câu có filter: 4 câu dev (q03–q06), 2 câu test (q21, q22). Filter là `{"year": 2012}` hoặc `{"year": 2019}`, lấy từ phiên bản luật mà **câu hỏi nêu rõ** ("Theo Bộ luật Lao động 2019, ..."), tức người dùng cung cấp trước khi truy xuất, không lấy từ gold. Giá trị `year` của mỗi chunk lấy từ số hiệu văn bản trong chính tài liệu (10/2012/QH13, 45/2019/QH14) và được đối chiếu với `data/sources.json`.

Các câu filter được chọn sao cho hai bản luật trả lời **khác nhau** (ví dụ giờ làm thêm/tháng: 30 giờ ở bản 2012, 40 giờ ở bản 2019), hoặc có đoạn gần giống ở bản kia, để đo được tác dụng của filter. Câu không có filter vẫn chạy không filter ở cấu hình C.

## Evidence

- Mỗi `evidence_quote` là đoạn **liên tục** chép nguyên văn từ văn bản đã chuẩn hóa (`data/processed/*.txt`). Khi đáp án là một điểm trong danh sách mà bản thân điểm đó không đủ điều kiện để trả lời, đoạn trích có cả câu dẫn của khoản (ví dụ q04, q11, q18, q21).
- Khi so khớp, khoảng trắng và chữ hoa/thường được chuẩn hóa (`evaluation.norm`).
- `check-benchmark` báo lỗi nếu evidence không có trong Điều gold, và cảnh báo nếu evidence xuất hiện nguyên văn ở một Điều khác chưa được ghi làm gold.
- Thay đổi trước khi chạy thử: lần kiểm tra đầu báo evidence cũ của q17 ("Hợp đồng lao động theo mùa vụ ... dưới 12 tháng.") xuất hiện nguyên văn ở Điều 38 bản 2012. q17 được đổi thành câu điều kiện chỉ Điều 22 trả lời được. Lúc đó chưa chạy truy xuất lần nào.

## Tiêu chí chọn chiến lược (chốt trước khi xem test)

Chọn trên **dev**, theo thứ tự:

1. Evidence Hit@3 trên dev cao hơn.
2. Nếu chênh lệch không quá 1 câu: Hit@1 trên dev.
3. Nếu vẫn hòa: ít chunk hơn / thời gian ingest ngắn hơn.

Test chỉ chạy **một lần** sau khi đã chốt lựa chọn trên dev, và không sửa cấu hình theo kết quả test.

## Người soạn

Câu hỏi được soạn với sự hỗ trợ của AI (Claude Code). Evidence được kiểm tra tự động bằng `check-benchmark` và cần tác giả đọc lại đối chiếu với văn bản gốc.
