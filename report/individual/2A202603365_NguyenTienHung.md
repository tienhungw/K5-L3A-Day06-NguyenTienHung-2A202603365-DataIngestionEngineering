# Báo cáo cá nhân — Day 6

Nguyễn Tiến Hưng · MSSV 2A202603365 · L3A

## Dữ liệu và pipeline

- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** Bộ luật Lao động 2012 (số 10/2012/QH13, file .doc của Sở Tư pháp Đắk Lắk) và Bộ luật Lao động 2019 (số 45/2019/QH14, trang HTML của cổng phổ biến pháp luật TP Cần Thơ). URL, ngày truy cập và sha256 của file gốc ở `data/sources.json` và `data/manifest.json`. Văn bản quy phạm pháp luật không thuộc phạm vi bảo hộ quyền tác giả (khoản 2 Điều 15 Luật Sở hữu trí tuệ), nên được sao chép, xử lý và đưa file gốc vào repo. Hai nguồn không phân trang, nên đơn vị truy vết là **một Điều** (lưu ở trường `page`). Chỉ tính từ Điều 1 đến Điều cuối, bỏ quốc hiệu, căn cứ ban hành, dòng thông qua, chữ ký và footer trang web. Kết quả: 462 Điều (242 + 220), 344.441 ký tự, tương đương khoảng 229 trang nếu tính 1.500 ký tự/trang.
- **Chuẩn hóa, lỗi và giới hạn:** Bản PDF trên cổng Chính phủ là ảnh scan không có lớp chữ nên không dùng. File .doc (Word 97) được đọc qua piece table bằng `olefile` và bỏ field code; HTML được tách đoạn bằng `html.parser`. Sau đó chuẩn hóa Unicode NFC, thay ký tự điều khiển, gộp khoảng trắng, rồi tách theo Điều và ghi lại Chương, Mục của từng Điều. Pipeline kiểm tra số Điều liên tục từ 1 đến N và số hiệu luật trong văn bản. Log ở `results/ingest_log.json`: 0 lỗi, 0 cảnh báo, có danh sách các dòng bị loại ở đầu và cuối mỗi văn bản. Lỗi gặp trong lúc làm: ở bản 2012, tiêu đề Chương/Mục dài hai dòng bị dính vào cuối Điều đứng trước; đã sửa và kiểm tra lại không còn dòng tiêu đề nào nằm trong Điều. Giới hạn: bản 2019 là bản gốc, chưa gồm các sửa đổi năm 2025; nguồn lấy từ cổng thông tin địa phương chứ không phải Công báo.
- **Embedding, vector store, metric, lệnh chạy, chi phí:** `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, 384 chiều, tối đa 512 token, chạy local trên CPU qua sentence-transformers 6.3.0 và torch 2.15.0+cpu. Query có tiền tố `query: `, chunk có tiền tố `passage: `, vector được chuẩn hóa. Vector store là Chroma 1.5.9 (PersistentClient, lưu ở `starter/vectordb/`), khoảng cách cosine, index HNSW (ef_construction 200, ef_search 100). Lệnh chạy ghi ở `README.md` (thư mục gốc). Chi phí 0 USD. Máy chạy: Windows 11, CPU Intel64 Family 6 Model 140, không GPU; load model mất 19,0 s.
- **Metadata:** trường bắt buộc là `document_id` (`blld-2012`, `blld-2019`), `source` (URL gốc) và `page` (số Điều). Trường lọc là `year`, lấy từ số hiệu văn bản trong chính tài liệu (10/2012/QH13, 45/2019/QH14) và đối chiếu với `data/sources.json`. Ngoài ra còn `law_number`, `article_title`, `chapter`, `section`, offset ký tự của Điều và của chunk, và `text_sha1` để phát hiện chunk thay đổi khi nạp lại. Chọn `year` vì hai bản luật có nhiều Điều gần giống nhau nhưng khác số liệu (ví dụ giới hạn giờ làm thêm theo tháng là 30 giờ ở bản 2012 và 40 giờ ở bản 2019), và người hỏi thường nói rõ mình hỏi theo bản nào.

## Cấu hình và benchmark

- **A / B / C:** A cắt cửa sổ cố định 500 ký tự, overlap 50, trong phạm vi từng Điều (942 chunk). B gom các khoản/điểm liên tiếp trong cùng một Điều, tối đa 800 ký tự; đoạn dài hơn thì tách theo câu (685 chunk). C dùng chung collection với B và chỉ thêm `where year = <năm>` khi câu hỏi nêu phiên bản luật. Khác biệt duy nhất giữa B và C là filter. Cả ba dùng cùng model, corpus, benchmark và top_k = 3. Tham số ở `starter/configs/strategies.json` và `artifacts/experiment_log.csv`.
- **Benchmark:** 25 câu trong `benchmark/questions.jsonl`, chia theo Chương trước khi chạy truy xuất: dev 18 câu (Chương I, II, III, VI, VII, XII), test 7 câu (Chương VIII, X, XI), nên không Điều nào vừa là gold của dev vừa là gold của test. Loại câu: trực tiếp 6, diễn đạt lại 6, điều kiện 7, metadata 6. Có 6 câu filter: q03–q06 (dev) và q21, q22 (test); giá trị filter lấy từ phiên bản luật mà câu hỏi nêu, không lấy từ gold. Evidence là đoạn chép nguyên văn từ văn bản đã chuẩn hóa. Lệnh `check-benchmark` kiểm tra 39 đoạn evidence (gồm cả nguồn thay thế `alt_gold` khi câu hỏi không nêu phiên bản và cả hai bản đều trả lời được): mỗi đoạn phải nằm trong Điều gold, và có cảnh báo nếu nó xuất hiện nguyên văn ở Điều khác chưa được ghi làm gold. Kết quả 0 lỗi, 0 cảnh báo (`results/benchmark_check.json`). Lần kiểm tra đầu tiên đã phát hiện evidence của q17 trùng với Điều 38 bản 2012, nên q17 được viết lại trước khi chạy truy xuất lần nào.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test** (`benchmark/README.md`): (1) Evidence Hit@3 trên dev; (2) nếu chênh lệch không quá 1 câu thì xét Hit@1 dev; (3) nếu vẫn hòa thì chọn cấu hình ít chunk hơn, ingest nhanh hơn. Test chỉ chạy một lần, sau khi đã ghi lựa chọn vào `results/selection_dev.md`.

## Kết quả

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/18 | 11/18 | 942 | ingest 54,0 s (embed 52,3 s) | 0 USD |
| A | test | 5/7 | 7/7 | 942 | (cùng lần ingest) | 0 USD |
| B | dev | 16/18 | 16/18 | 685 | ingest 51,5 s (embed 50,1 s) | 0 USD |
| B | test | 7/7 | 7/7 | 685 | (cùng lần ingest) | 0 USD |
| C | dev | 16/18 | 17/18 | 685 (chung với B) | không ingest thêm | 0 USD |
| C | test | 7/7 | 7/7 | 685 (chung với B) | không ingest thêm | 0 USD |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,9 (10) | 21/21 | 0/2 | 0/1/6, 1,86 |
| B | 1,7 (10) | 21/21 | 0/2 | 0/0/7, 2,00 |
| C | 1,7 (10) | 21/21 | 2/2 | 0/0/7, 2,00 |

Hit chỉ được tính khi chunk thuộc đúng nguồn và đúng Điều gold **và** chứa trọn evidence (đã chuẩn hóa khoảng trắng, chữ hoa/thường). Tìm kiếm HNSW được đối chiếu với tìm kiếm chính xác bằng numpy: trùng 162/162 kết quả trên dev và 61/63 trên test (hai chỗ lệch đều ở hạng 3 của q20, không đổi hit). Thời gian truy vấn in ra khi evaluate có cả bước đối chiếu này nên không dùng làm độ trễ.

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:

- Trace top-3 (câu hỏi, chunk ID, text, score, metadata, nhãn hit): `results/traces/{A,B,C}_{dev,test}.jsonl`; chỉ số: `results/metrics_{dev,test}.json`, `results/per_question_{dev,test}.csv`.
- Nhãn: `results/audit/coherence.csv`, `metadata.csv`, `grounding.csv`; tổng hợp: `results/audit_summary.json`; phân tích chi tiết: `results/analysis.md`.
- Coherence: 10 vị trí chọn bằng `random.Random(6)` trong các Điều dài ít nhất 1.000 ký tự, mỗi vị trí là ký tự ở giữa Điều. Quy tắc này được cố định trong code (`cmd_audit` trong `starter/src/run.py`) trước khi xem điểm, và cả ba chiến lược dùng cùng 10 vị trí. Metadata: 7 câu test × top-3 = 21 bản ghi mỗi chiến lược. Grounding: 7 câu test, chấm top-3. Thang điểm theo GUIDE, có lý do ở từng dòng.
- Cách chấm: các cột `auto_*` do code tính (text có đúng offset trong văn bản nguồn không, `source`/`year` có khớp manifest không, tiêu đề Điều có khớp không, evidence có nằm trong top-3 không) để đối chiếu với nhãn tay. Nhãn 0/1/2 được Claude Code chấm nháp theo thang của GUIDE; người chấm và trạng thái duyệt ghi ở cột `labeler`. Người soạn câu hỏi và người chấm cùng phía với người thiết kế chunking, nên có nguy cơ thiên lệch.

## Phân tích và kết luận

- **So sánh A–B (đổi cách chia chunk):** Hit@3 dev tăng từ 11/18 lên 16/18, coherence từ 0,9 lên 1,7, số chunk giảm 27% (942 xuống 685), thời gian ingest gần như nhau (54,0 s và 51,5 s). Cả 7 câu A trượt trên dev đều đã có đúng Điều trong top-3 nhưng evidence bị chia giữa hai cửa sổ: overlap 50 ký tự không đủ cho evidence dài 134–404 ký tự. Cả 10/10 chunk A trong mẫu coherence bắt đầu hoặc kết thúc giữa câu. Đánh đổi: chunk B dài hơn (trung bình 503 so với 391 ký tự), nên mỗi kết quả đưa nhiều văn bản hơn vào ngữ cảnh.
- **So sánh B–C (thêm filter `year`):** không đổi chunk, không tốn thêm lưu trữ hay thời gian ingest. Câu không có filter cho top-3 giống hệt B (dev 14/14, test 5/5). Ở câu có filter, Hit@3 dev tăng từ 2/4 lên 3/4, test giữ 2/2; top-3 đúng năm được hỏi tăng từ 0/4 lên 4/4 (dev) và từ 0/2 lên 2/2 (test). Ở q21 và q22 (test), B vẫn có chunk của bản luật không được hỏi trong top-3; ở q21, bản 2012 không có ngoại lệ "được người lao động đồng ý" như bản 2019, nên người đọc có thể lấy nhầm quy định.
- **Ví dụ sai:**
  1. **q04** (dev, filter 2019; gold: `blld-2019`, Điều 35): B và C đều trượt. Câu dẫn "2. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động không cần báo trước trong trường hợp sau đây:" bị gom vào chunk `B:blld-2019:D035:00` cùng khoản 1, còn các điểm a), b) nằm ở `B:blld-2019:D035:01`. Chunk được truy xuất có điểm b nhưng thiếu câu dẫn, tức chỉ có khoảng 295/404 ký tự evidence. Không lọc thì B còn xếp `blld-2012` Điều 38 (quyền đơn phương chấm dứt của người sử dụng lao động) lên hạng 1. Nguyên nhân: cách gom tham lam để câu dẫn của danh sách dính vào nhóm phía trước.
  2. **q03** (dev, filter 2012; gold: `blld-2012`, Điều 22): B trượt, C trúng. Không lọc thì top-3 là `blld-2012:D022:01`, `blld-2019:D020:01` và `blld-2019:D036:01`; chunk chứa định nghĩa "từ đủ 12 tháng đến 36 tháng" (`blld-2012:D022:00`) bị đẩy ra ngoài. Khi lọc `year = 2012`, hai chunk bản 2019 bị loại và `D022:00` lên hạng 2.
  3. **q18** (dev; gold: `blld-2019`, Điều 107): A trượt, B trúng. Evidence dài 341 ký tự (câu dẫn khoản 3 cùng điểm a, b); cửa sổ `A:blld-2019:D107:01` chỉ chứa khoảng 185 ký tự đầu.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** chọn **C** (`results/selection_dev.md`, ghi trước khi chạy test). A bị loại ở bước 1 của tiêu chí. B (16/18) và C (17/18) chênh 1 câu, Hit@1 bằng nhau (16/18) và dùng chung index, nên tiêu chí đã chốt không phân định được. Quyết định bổ sung trên dev là chọn C, vì C không làm xấu câu không filter và top-3 luôn đúng phiên bản được hỏi. Trên test, B và C cùng 7/7 Hit@3; khác biệt chỉ còn ở mức tuân thủ filter (2/2 so với 0/2). C chỉ có ích khi người dùng nêu rõ phiên bản luật; nếu giá trị filter sai thì đáp án đúng bị loại hoàn toàn (trường hợp này chưa được đo).
- **Hạn chế:** mẫu nhỏ (18 câu dev, trong đó 4 câu filter; 7 câu test, trong đó 2 câu filter), chênh lệch 1 câu không có ý nghĩa thống kê, và test có thể dễ hơn dev. Định nghĩa hit đòi chứa trọn evidence nên bất lợi cho chunk nhỏ khi evidence dài. `page` là số Điều chứ không phải số trang. `year` chỉ có hai giá trị trùng với hai văn bản, nên filter thực chất là chọn văn bản. Thời gian đo trên một máy, chạy một lần. Nhãn thủ công chỉ có một người chấm, chưa đo độ đồng thuận.
- **Nếu làm lại hoặc mở rộng:**
  - Sửa cách gom của B để câu dẫn kết thúc bằng dấu ":" luôn đi cùng các điểm phía sau (lỗi q04).
  - Thêm tiêu đề Điều vào đầu mỗi chunk khi embed, vì chunk B ở giữa Điều mất điểm coherence khi thiếu tiêu đề (P03, P09).
  - Tự nhận diện phiên bản luật trong câu hỏi thay vì khai báo filter sẵn, và đo trường hợp filter sai.
  - Tăng số câu test, nhất là câu filter, và nhờ người thứ hai chấm nhãn để đo độ đồng thuận.
  - Thêm văn bản hợp nhất có sửa đổi năm 2025 nếu tìm được nguồn có lớp chữ.

## Công cụ AI và cách kiểm tra

Dùng Claude Code (Anthropic) để viết code pipeline, soạn nháp câu hỏi benchmark, chấm nháp nhãn thủ công và soạn nháp báo cáo này từ số liệu trong `results/`. Cách kiểm tra:

- Evidence: `check-benchmark` xác nhận từng đoạn nằm trong Điều gold.
- Chunking: kiểm tra trên toàn corpus rằng offset của chunk khớp văn bản nguồn, không chunk nào vượt giới hạn, các chunk phủ hết nội dung từng Điều và không trùng ID.
- Vector store: so khoảng cách Chroma trả về với 1 − cos tính bằng numpy, và so HNSW với tìm kiếm chính xác.
- Nạp lại: chạy `ingest` lần hai thì 942/685 chunk được báo không đổi, số bản ghi giữ nguyên. Script `starter/scripts/reingest_change_test.py` thử trên store tạm với 20 Điều: sửa Điều 5 thì chỉ 1 chunk được embed lại, xóa Điều 10 thì chunk của nó bị xóa, đổi metadata Điều 3 thì 5 chunk được cập nhật mà không embed lại (`results/reingest_change_test.json`).
- Nhãn thủ công: đối chiếu với các cột `auto_*`; người chấm ghi ở cột `labeler`.
