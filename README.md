# Clipboard AI Overlay

Ứng dụng desktop thử nghiệm hiển thị phản hồi AI trong một overlay nhỏ khi bạn chủ động gửi nội dung từ clipboard. Ứng dụng chạy trên máy của bạn; token, endpoint và lựa chọn model là cấu hình riêng trong `.env`, không được đưa vào repository.

## Chức năng

- Bật hoặc tắt theo dõi clipboard bằng biểu tượng system tray.
- Gửi văn bản đang chọn bằng phím `R`, hoặc gửi ảnh trong clipboard bằng phím `A`.
- Hiển thị phản hồi ngắn trong overlay có thể kéo thả.
- Nhận diện các câu được đánh số rõ ràng (`Câu 1`, `Question 2`, …), gửi từng câu độc lập và hiện đáp án theo thứ tự hoàn thành.
- OCR ảnh cục bộ để hỗ trợ tìm tài liệu và tách nhiều câu; khi không tách chắc chắn, ảnh gốc vẫn được gửi để AI đọc theo bố cục.
- Tìm trong `resources/` trước; web fallback chỉ được dùng khi bạn chủ động bật.
- Bỏ qua một số chuỗi nhạy cảm rõ ràng trong văn bản trước khi gửi.

## Yêu cầu

- Python 3.12 trở lên.
- Môi trường desktop có system tray.
- Một tài khoản/dịch vụ AI tương thích với endpoint Responses hoặc Chat Completions.
- Token truy cập và tên model do **bạn tự cấu hình cục bộ**. Repository không kèm các giá trị này hay file trọng số model.

Trên Linux, các phím tắt toàn cục (`Left Shift`, `R`, `A`) cần phiên X11 và biến `DISPLAY`. Nếu dùng Wayland hoặc phím tắt không hoạt động, bạn vẫn có thể sử dụng các mục tương ứng trong tray menu.

## Cài đặt

```bash
git clone https://github.com/ThienDZN/Tool-mionitor-for-dcd-.git
cd Tool-mionitor-for-dcd-
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
```

Mở `.env` trên máy của bạn và điền hai biến bắt buộc `OPENAI_API_KEY` và `OPENAI_MODEL` bằng thông tin của tài khoản riêng. Không dán các giá trị đó vào issue, ảnh chụp màn hình, commit hoặc pull request.

Các tuỳ chọn đáng chú ý:

| Biến | Mặc định trong template | Tác dụng |
| --- | --- | --- |
| `AUTO_START_MONITORING` | `0` | Chỉ bật theo dõi sau khi bạn chọn trong tray. |
| `ENABLE_WEB_FALLBACK` | `0` | Cho phép ứng dụng yêu cầu tìm kiếm web khi không tìm thấy tài liệu local. |
| `MAX_CLIPBOARD_CHARS` | `12000` | Cắt ngắn văn bản clipboard trước khi gửi; đủ cho nhiều câu hơn. |
| `MAX_RESPONSE_CHARS` | `480` | Giới hạn độ dài phản hồi hiển thị. |
| `REQUEST_TIMEOUT_S` | `40` | Thời gian chờ một yêu cầu mạng, tính bằng giây. |
| `PER_QUESTION_TIME_BUDGET_S` | `60` | Ngân sách tối đa 1 phút cho một câu, gồm retry và kiểm tra ảnh nếu còn thời gian. |
| `MAX_PARALLEL_QUESTIONS` | `8` | Số câu tối đa gửi đồng thời khi nhận diện chắc chắn nhiều câu; đây là giới hạn cục bộ, không phải quota nhà cung cấp. |

Để dùng endpoint tương thích riêng, bỏ comment và cấu hình `OPENAI_BASE_URL` trong `.env`. `OPENAI_REASONING_EFFORT` là tuỳ chọn; chỉ đặt nó nếu dịch vụ của bạn hỗ trợ.

## Chạy ứng dụng

```bash
./run.sh
```

Khi khởi động, ứng dụng chỉ hỏi một lần: **“Môn học tên gì?”** để ưu tiên tài liệu local. Sau đó biểu tượng tray xuất hiện.

| Thao tác | Kết quả |
| --- | --- |
| Nhấp trái biểu tượng tray | Bật/tắt theo dõi clipboard. |
| Sao chép văn bản khi monitoring bật | Gửi văn bản mới đến dịch vụ AI đã cấu hình. |
| `R` | Gửi văn bản đang bôi đen trên X11; nếu không có, gửi text clipboard. |
| `A` | Gửi ảnh đang có trong clipboard. |
| `Left Shift` | Ẩn/hiện overlay trên X11. |
| `Refresh resources` trong tray | Đọc lại tài liệu trong `resources/`. |

Khi một yêu cầu đang chạy, ứng dụng chỉ giữ yêu cầu mới nhất để gửi sau đó. Sau khi bấm `R` hoặc `A`, overlay báo **ĐANG NHẬN DIỆN CÂU HỎI...**; khi nhận ra, ví dụ `Câu 31–34`, nó hiện từng dòng `Câu 31: RUNNING`… Trong lúc chạy, đáp án nào xong trước sẽ được đưa lên đầu, còn các câu chưa xong vẫn hiển thị `RUNNING`. Các câu được xử lý độc lập với số luồng tối đa do `MAX_PARALLEL_QUESTIONS` đặt ra. OCR giờ giữ ảnh tới 2400px và 12.000 ký tự để nhận diện nhiều câu nhỏ hơn; văn bản hỗ trợ `Câu31`, `Câu hỏi 31`, `Question No. 31`, `Q31` và số thứ tự rõ ràng. Văn bản hoặc ảnh mơ hồ vẫn được gửi nguyên khối để tránh tách nhầm đáp án/lựa chọn thành câu hỏi.

## Tài liệu local

Đặt tài liệu theo chủ đề vào thư mục `resources/`. Các định dạng được hỗ trợ là `.txt`, `.md`, `.pdf` và `.docx`.

1. Thêm tài liệu vào `resources/`.
2. Chạy ứng dụng hoặc chọn `Refresh resources` trong tray.
3. Khi gửi nội dung, ứng dụng sẽ tìm các đoạn liên quan trong tài liệu local trước.

`resources/` bị Git ignore (trừ file hướng dẫn), vì tài liệu của bạn có thể là dữ liệu riêng tư hoặc có bản quyền.

## Quyền riêng tư và an toàn dữ liệu

- Text clipboard chỉ được gửi khi monitoring đang bật hoặc khi bạn chủ động dùng `R`.
- Ảnh clipboard chỉ gửi khi bạn dùng `A` hoặc hành động tương ứng trong tray.
- Nội dung gửi đi, đoạn trích từ `resources/`, và web fallback (nếu bật) có thể rời khỏi máy để đến dịch vụ AI của bạn. Không gửi mật khẩu, token, thông tin cá nhân, nội dung công việc nhạy cảm hoặc ảnh có thông tin bí mật.
- Bộ lọc hiện chỉ nhận ra một số mẫu secret trong **văn bản**; nó không phải cơ chế bảo vệ tuyệt đối, đặc biệt với ảnh hoặc văn bản OCR.
- `.env`, trạng thái chạy, tài liệu `resources/`, virtual environment và cache đều bị ignore. Trước mỗi commit, kiểm tra lại bằng `git status`.

Nếu token từng bị commit hoặc công khai, hãy thu hồi/rotate token đó ngay tại nhà cung cấp rồi xoá nó khỏi lịch sử Git trước khi public repository.

## Khắc phục sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| Báo thiếu cấu hình | Kiểm tra `.env` có hai biến bắt buộc và không để trống; sau đó khởi động lại ứng dụng. |
| Không thấy tray icon | Dùng desktop session có hỗ trợ system tray. |
| `R`, `A` hoặc `Left Shift` không hoạt động | Kiểm tra đang dùng X11 và có `DISPLAY`; nếu không, dùng tray menu. |
| Báo `429` / rate limit | `MAX_PARALLEL_QUESTIONS=8` chỉ tăng số yêu cầu cục bộ; quota thật do nhà cung cấp quyết định. Ứng dụng tôn trọng `Retry-After` và retry backoff, nhưng nếu vẫn lặp lại hãy giảm giá trị này. |
| Ứng dụng không phản hồi | Kiểm tra mạng, endpoint cục bộ, quyền token; điều chỉnh `REQUEST_TIMEOUT_S` và `PER_QUESTION_TIME_BUDGET_S` nếu cần. |
| Không tìm thấy tài liệu mới | Bảo đảm file nằm trong `resources/`, dùng định dạng hỗ trợ, rồi chọn `Refresh resources`. |

## Cấu trúc chính

```text
src/clip_overlay_ai/  Mã nguồn ứng dụng
docs/                 Tài liệu kiến trúc và tài nguyên
resources/            Tài liệu local của người dùng (không commit)
.env.example          Mẫu cấu hình không chứa secret hay model cụ thể
```
