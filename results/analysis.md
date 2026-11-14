# Kết quả và phân tích năm khía cạnh

Corpus: Bộ luật Lao động 2012 (242 Điều) và 2019 (220 Điều), 462 đơn vị, 344.441 ký tự. Model `intfloat/multilingual-e5-small` (revision `614241f6…`, 384 chiều, CPU). Store: Chroma 1.5.9 PersistentClient, cosine, HNSW (ef_construction 200, ef_search 100, M 16). Chạy ngày 2026-11-14 trên Windows 11, CPU "Intel64 Family 6 Model 140", không GPU. Chi phí: 0 USD (model chạy local).

Nguồn số liệu: `ingest_stats.json`, `metrics_dev.json`, `metrics_test.json`, `per_question_*.csv`, `traces/*.jsonl`, `audit/*.csv`, `audit_summary.json`.

## Cấu hình

| | Chunking | Truy xuất | Collection |
|---|---|---|---|
| A | cửa sổ cố định 500 ký tự, overlap 50, trong từng Điều | không lọc | `blld_A_fixed500_o50` |
| B | gom đoạn (khoản/điểm) liên tiếp trong từng Điều, tối đa 800 ký tự; đoạn dài hơn tách theo câu | không lọc | `blld_B_para800` |
| C | giống B (cùng collection) | `where year = <năm>` khi câu hỏi nêu phiên bản luật | `blld_B_para800` |

A–B thay đổi cách chia chunk (cả quy tắc ranh giới lẫn giới hạn kích thước). B–C chỉ khác ở filter.

## 1. Độ chính xác truy xuất

| Strategy | Split | Hit@1 | Evidence Hit@3 | Điều gold có trong top-3 | Evidence bị tách |
|---|---|---|---|---|---|
| A | dev | 11/18 | 11/18 | 18/18 | 7 |
| B | dev | 16/18 | 16/18 | 18/18 | 2 |
| C | dev | 16/18 | 17/18 | 18/18 | 1 |
| A | test | 5/7 | 7/7 | 7/7 | 0 |
| B | test | 7/7 | 7/7 | 7/7 | 0 |
| C | test | 7/7 | 7/7 | 7/7 | 0 |

- "Điều gold có trong top-3" nghĩa là đúng văn bản và đúng Điều, chưa xét evidence. A luôn tìm đúng Điều (18/18), nhưng 7 câu dev trượt vì không chunk nào chứa trọn evidence.
- HNSW và tìm kiếm chính xác (numpy, cùng filter) trùng 162/162 kết quả trên dev và 61/63 trên test. Hai trường hợp lệch là hạng 3 của q20 ở B và C (điểm 0,8805, sát ứng viên khác), không ảnh hưởng hit.

## 2. Độ mạch lạc của chunk (chấm tay, 10 vị trí)

10 vị trí được chọn bằng `random.Random(6)` trong các Điều dài ít nhất 1.000 ký tự; mỗi vị trí là ký tự giữa Điều. Quy tắc mẫu được cố định trong code (`run.py`, `cmd_audit`) trước khi xem điểm. Thang điểm và lý do từng dòng ở `audit/coherence.csv`.

| Strategy | Nhãn (P01…P10) | Trung bình /2 |
|---|---|---|
| A | 1,0,1,1,1,1,1,1,1,1 | 0,9 |
| B (= C) | 2,1,1,2,2,2,2,2,1,2 | 1,7 |

Cả 10/10 chunk của A bắt đầu hoặc kết thúc giữa câu (9 chunk bắt đầu giữa câu hoặc giữa từ), và P02 mất đúng phần kết luận của khoản. B chỉ mất điểm khi chunk thiếu tiêu đề Điều (P03, P09) hoặc phụ thuộc "điểm b, c khoản 1 Điều này" (P02).

## 3. Tính hữu dụng của metadata (test: 7 câu × top-3)

| Strategy | Metadata đủ và đúng | Top-3 tuân thủ filter |
|---|---|---|
| A | 21/21 | 0/2 |
| B | 21/21 | 0/2 |
| C | 21/21 | 2/2 |

- Mỗi bản ghi được đối chiếu: text nằm đúng offset trong `data/processed/<source>.txt` và có trong file gốc; `source` khớp manifest; `year` và `law_number` khớp số hiệu trong văn bản; `article_title` khớp dòng tiêu đề Điều; `chapter` khớp tiêu đề Chương đứng trước Điều. Không có lỗi.
- Trường giúp truy vết: `page` (số Điều) cùng `article_title` cho phép trích dẫn kiểu "Điều 137 Bộ luật Lao động 2019".
- Trường giúp lọc: `year`. Ở q21 và q22 (test), B có lần lượt 1 và 2 chunk thuộc bản luật không được hỏi trong top-3; C không có.
- Hạn chế: `page` là số Điều chứ không phải số trang, vì nguồn không phân trang. `year` chỉ có 2 giá trị và trùng với văn bản, nên filter thực chất là chọn văn bản. `section = 0` khi Chương không chia Mục.

## 4. Chất lượng grounding (chấm tay, 7 câu test × top-3)

| Strategy | 0 / 1 / 2 (số câu) | Trung bình /2 |
|---|---|---|
| A | 0 / 1 / 6 | 1,86 |
| B | 0 / 0 / 7 | 2,00 |
| C | 0 / 0 / 7 | 2,00 |

Đây là đánh giá độ đủ của bằng chứng truy xuất, không phải độ chính xác câu trả lời của LLM. A được 1 ở q25: chunk bản 2019 bị cắt ngay sau "30 ngày hoặc". Ở B, q21 và q22 được 2 nhưng top-3 lẫn bản luật khác năm với quy định khác (q21: bản 2012 không có ngoại lệ "được người lao động đồng ý"); C không gặp vấn đề này.

## 5. Tác động của chiến lược dữ liệu

### A → B (đổi cách chia chunk)

| | A | B |
|---|---|---|
| Số chunk | 942 | 685 (−27%) |
| Ký tự/chunk: median, mean, max | 499 / 391 / 500 | 528 / 503 / 800 |
| Tổng ký tự / token (e5 tokenizer) | 368.217 / 97.753 | 344.218 / 90.195 |
| Chunk bị cắt do vượt 512 token | 0 | 0 |
| Thời gian embed / tổng ingest (giây) | 52,3 / 54,0 | 50,1 / 51,5 |
| Dev Hit@3 | 11/18 | 16/18 |
| Coherence | 0,9 | 1,7 |

- Hit@3 dev tăng 5 câu. Cả 7 câu A trượt trên dev đều do evidence bị chia giữa hai cửa sổ, dù đúng Điều đã có trong top-3. Overlap 50 ký tự không đủ cho evidence dài 134–404 ký tự.
- B ít chunk hơn và tổng ký tự thấp hơn vì không lặp phần overlap. Thời gian ingest gần như nhau (khoảng 51–54 giây), nên với corpus này tài nguyên không phải yếu tố quyết định.
- Đánh đổi: chunk B dài hơn (mean 503 so với 391 ký tự), nên mỗi kết quả đưa thêm văn bản vào ngữ cảnh.

### B → C (thêm filter `year`)

- Không đổi chunk, không tốn thêm lưu trữ hay thời gian ingest. Câu không có filter cho kết quả giống hệt nhau (dev 14/14, test 5/5).
- Ở câu có filter: Hit@3 dev 2/4 → 3/4 (q03), test 2/2 → 2/2. Top-3 đúng năm được hỏi: dev 0/4 → 4/4, test 0/2 → 2/2.
- Điều kiện: chỉ có ích khi người dùng nêu rõ phiên bản. Nếu giá trị filter sai thì đáp án đúng bị loại hoàn toàn (chưa được đo).

### Ví dụ lỗi

1. **q04 (dev, filter 2019), B và C trượt — evidence bị tách theo ranh giới nhóm.** Ở Điều 35 bản 2019, câu dẫn "2. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động không cần báo trước trong trường hợp sau đây:" bị gom vào chunk `B:blld-2019:D035:00` cùng khoản 1. Các điểm a), b) nằm ở `…D035:01`. Chunk được truy xuất chứa điểm b nhưng không có câu dẫn "không cần báo trước", nên chỉ có khoảng 295/404 ký tự evidence. Thêm vào đó, B xếp `blld-2012:D038` (quyền đơn phương chấm dứt của người sử dụng lao động, bản 2012) lên hạng 1. Đây là lỗi của cách gom tham lam: câu dẫn của danh sách dính vào nhóm trước.
2. **q03 (dev, filter 2012), B trượt, C trúng — nhầm phiên bản.** Không lọc thì top-3 là `blld-2012:D022:01` (khoản 2 về hợp đồng hết hạn), `blld-2019:D020:01` và `blld-2019:D036:01`. Chunk chứa định nghĩa "từ đủ 12 tháng đến 36 tháng" (`blld-2012:D022:00`) bị đẩy ra ngoài. Khi lọc `year=2012`, hai chunk bản 2019 bị loại và `D022:00` lên hạng 2.
3. **q18 (dev), A trượt, B trúng.** Evidence 341 ký tự (câu dẫn khoản 3 Điều 107 bản 2019 cùng điểm a, b). Cửa sổ `A:blld-2019:D107:01` chỉ chứa khoảng 185 ký tự đầu, còn B giữ trọn khoản trong một chunk.
4. **q25 (test), A sai ở Hit@1.** Top-1 là `A:blld-2012:D155:01` (cấm sa thải lao động nữ khi mang thai): trùng từ khóa "sa thải" nhưng không liên quan. Chunk bản 2019 (`A:blld-2019:D125:01`) bị cắt sau "05 ngày cộng dồn trong thời hạn 30 ngày hoặc".

### Lựa chọn

Chọn **C** theo `results/selection_dev.md`, ghi trước khi chạy test. Tiêu chí đã chốt cho B và C hòa; C được chọn vì không làm xấu câu không filter và tuân thủ filter 4/4 trên dev. Test (7/7 cho cả B và C) không phân biệt được hai cấu hình về Hit@3; khác biệt chỉ thể hiện ở mức tuân thủ filter (2/2 so với 0/2).

## Giới hạn

- Mẫu nhỏ: 18 câu dev (4 câu filter), 7 câu test (2 câu filter). Chênh lệch 1 câu không có ý nghĩa thống kê, và test có thể dễ hơn dev (cả B và C đều 7/7).
- Câu hỏi, evidence và nhãn chấm tay (coherence, metadata, grounding) là bản nháp do Claude (AI) soạn và chấm theo quy tắc ghi trong file; cần tác giả đọc lại và sửa. Người soạn câu hỏi cũng là người thiết kế chunking, nên có nguy cơ thiên lệch.
- Định nghĩa hit yêu cầu chứa trọn evidence, nên bất lợi cho chunk nhỏ khi evidence dài (q04: 404 ký tự).
- Corpus không phân trang: `page` là số Điều. Các văn bản lấy từ cổng thông tin của địa phương (Đắk Lắk, Cần Thơ) vì bản PDF chính thức là ảnh scan. Bản 2019 là bản gốc, chưa gồm các sửa đổi năm 2025.
- Thời gian đo trên một máy, chạy một lần; thời gian truy vấn in ra khi evaluate gồm cả bước kiểm tra exact search nên không dùng làm độ trễ.
