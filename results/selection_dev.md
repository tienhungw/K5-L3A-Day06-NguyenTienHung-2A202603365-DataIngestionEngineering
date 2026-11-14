# Chọn chiến lược trên dev (ghi trước khi chạy test)

Nguồn số liệu: `results/metrics_dev.json`, `results/per_question_dev.csv`, trace ở `results/traces/*_dev.jsonl`.

| Strategy | Hit@1 | Evidence Hit@3 | Điều gold trong top-3 | Hit@3 câu có filter | Top-3 tuân thủ filter |
|---|---|---|---|---|---|
| A | 11/18 | 11/18 | 18/18 | 1/4 | 0/4 |
| B | 16/18 | 16/18 | 18/18 | 2/4 | 0/4 |
| C | 16/18 | 17/18 | 18/18 | 3/4 | 4/4 |

Áp dụng tiêu chí đã chốt trong `benchmark/README.md`:

1. Evidence Hit@3: A (11) thấp hơn hẳn B và C, nên loại A. B (16) và C (17) chênh 1 câu.
2. Chênh lệch không quá 1 câu nên xét Hit@1: B = C = 16/18.
3. Số chunk / thời gian ingest: B và C dùng chung một index (685 chunk), nên vẫn hòa.

Tiêu chí đã chốt **không phân định được B và C**. Quyết định bổ sung, đưa ra sau khi xem dev và **trước khi chạy test**: chọn **C**, vì:

- Với câu không có filter, C cho kết quả giống hệt B (14/14 câu trùng top-3). C chỉ khác B ở câu người dùng nêu phiên bản luật.
- Ở 4 câu có filter, top-3 của C luôn đúng năm được hỏi (4/4), còn B là 0/4. Evidence Hit@3 trên nhóm này là 3/4 so với 2/4.

Giới hạn: lựa chọn dựa trên 18 câu dev, trong đó chỉ có 4 câu filter. Chênh lệch 1 câu không có ý nghĩa thống kê.

Test được chạy một lần sau khi ghi file này; không chỉnh cấu hình theo kết quả test.
