# Clipboard AI Overlay

Copy một câu hỏi hoặc chụp màn hình câu hỏi, đáp án sẽ hiện trong một khung nhỏ nổi trên màn hình. Không cần bấm phím gửi.

Ứng dụng chạy trên máy của bạn và gọi tới dịch vụ AI **do bạn tự cấu hình** (token, model, endpoint nằm trong `.env` cục bộ, không có trong repository).

- [Bắt đầu nhanh](#bắt-đầu-nhanh)
- [Cách dùng hằng ngày](#cách-dùng-hằng-ngày)
- [Phím tắt và menu tray](#phím-tắt-và-menu-tray)
- [Các tình huống thường gặp](#các-tình-huống-thường-gặp)
- [Đọc khung đáp án](#đọc-khung-đáp-án)
- [Tài liệu local](#tài-liệu-local)
- [Cấu hình](#cấu-hình)
- [Quyền riêng tư](#quyền-riêng-tư)
- [Khắc phục sự cố](#khắc-phục-sự-cố)

## Bắt đầu nhanh

**Yêu cầu**

- Linux (X11 hoặc Wayland) có system tray. Windows/macOS chưa được kiểm thử.
- Python **3.12**. Python 3.13 trở lên chưa chạy được vì `rapidocr_onnxruntime` chưa hỗ trợ. Nếu máy chỉ có Python mới hơn, dùng [uv](https://docs.astral.sh/uv/) như bên dưới.
- Một dịch vụ AI tương thích endpoint Responses hoặc Chat Completions, cùng token và tên model của riêng bạn.

**1. Cài đặt**

```bash
git clone https://github.com/ThienDZN/Tool-mionitor-for-dcd-.git
cd Tool-mionitor-for-dcd-
python3.12 -m venv .venv          # hoặc: uv venv --seed --python 3.12 .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
cp .env.example .env
```

**2. Điền cấu hình**

Mở `.env` và điền hai dòng bắt buộc:

```ini
OPENAI_API_KEY=<token của bạn>
OPENAI_MODEL=<tên model>
```

Nếu dùng endpoint riêng, bỏ comment và điền thêm `OPENAI_BASE_URL`. Không dán các giá trị này vào issue, ảnh chụp màn hình hay commit.

**3. (Chỉ Wayland) Cho phép đọc phím tắt**

Trên Wayland, phím tắt cần quyền đọc `/dev/input`:

```bash
sudo usermod -aG input $USER
```

Sau đó đăng xuất rồi đăng nhập lại. Lệnh này cho mọi chương trình chạy dưới user của bạn đọc được phím bấm; nếu không muốn, bỏ qua bước này. Ứng dụng vẫn trả lời bình thường, chỉ mất phím tắt.

**4. Chạy**

```bash
./run.sh
```

Ứng dụng hỏi **“Môn học tên gì?”** (để ưu tiên tài liệu đúng môn), rồi hiện biểu tượng trên tray. **Nhấp trái vào biểu tượng tray để bật monitoring.** Từ lúc này, cứ copy hoặc chụp màn hình là có đáp án.

## Cách dùng hằng ngày

1. **Bật monitoring** bằng cách nhấp trái biểu tượng tray (nhấp lần nữa để tắt).
2. **Lấy câu hỏi** bằng một trong hai cách:
   - Bôi đen câu hỏi rồi `Ctrl+C`.
   - Chụp màn hình vùng có câu hỏi **vào clipboard** (ví dụ công cụ chụp màn hình của hệ thống với tuỳ chọn copy, hoặc Flameshot).
3. **Xem đáp án**: khung overlay hiện `ĐANG NHẬN DIỆN CÂU HỎI...`, sau đó là `RUNNING`, rồi tới đáp án.
4. **Câu tiếp theo**: chờ câu hiện tại xong rồi copy hoặc chụp câu mới. Muốn bỏ câu đang chạy thì bấm **`H` trước**, sau đó mới copy hoặc chụp.

> **Quy tắc quan trọng:** khi một câu đang chạy, mọi thứ bạn copy hoặc chụp thêm đều **bị bỏ qua**, không xếp hàng chờ. Nhờ vậy một ảnh chụp nhầm không bao giờ đè lên đáp án. Khung overlay sẽ nhắc: *“Đang chạy câu trước — bấm H để hủy rồi chụp/copy lại”*.

## Phím tắt và menu tray

| Phím / thao tác | Tác dụng |
| --- | --- |
| Nhấp trái biểu tượng tray | Bật/tắt monitoring. |
| `Ctrl+C` văn bản (monitoring bật) | Tự gửi văn bản. |
| Chụp màn hình vào clipboard (monitoring bật) | Tự đọc chữ trong ảnh (OCR), nhận diện câu hỏi và gửi. |
| `Left Shift` | Ẩn/hiện khung đáp án. |
| `H` khi **đang chạy** | Hủy câu đang chạy. Sau đó copy/chụp câu mới. |
| `H` ngay sau khi app **bỏ qua vì trùng** (trong 60 giây) | Vẫn gửi câu vừa bị bỏ qua. |
| `H` lúc khác | Không làm gì, nên gõ chữ "h" bình thường không ảnh hưởng. |
| Menu tray → `Resend clipboard text` / `Resend clipboard image` | Gửi lại nội dung đang có trong clipboard, bỏ qua bộ chống trùng. |
| Menu tray → `Refresh resources` | Đọc lại tài liệu trong `resources/`. |

Nếu phím tắt không hoạt động, việc gửi vẫn chạy bình thường vì nó dựa vào clipboard, không dựa vào phím.

## Các tình huống thường gặp

**Chụp nhầm ảnh hoặc copy nhầm câu.**
Bấm `H` để hủy, rồi chụp hoặc copy lại câu đúng. Nếu bạn đã chụp câu đúng trước khi bấm `H`, câu đó đã bị bỏ qua; hãy chụp hoặc copy lại sau khi bấm `H`.

**Chụp ảnh câu hỏi xong lại copy text của chính câu đó.**
App nhận ra đây là câu vừa trả lời (trong 45 giây) và không gửi lần hai. Khung overlay hiện lại đáp án cũ kèm dòng *“Trùng câu vừa trả lời — bấm H để gửi lại”*.

**App bỏ qua một câu mới vì tưởng là câu cũ.**
Có thể xảy ra khi hai câu gần giống hệt nhau. Bấm `H` trong vòng 60 giây để gửi câu đó.

**Muốn hỏi lại đúng câu vừa hỏi.**
Bấm `H` ngay sau khi app báo trùng, hoặc dùng `Resend clipboard ...` trong menu tray.

**Copy từ Word, WPS hoặc trình duyệt.**
Các app này thường đưa cả chữ lẫn ảnh vào clipboard. App ưu tiên gửi **chữ**.

**Một ảnh chứa nhiều câu (`Câu 31`, `Câu 32`, …).**
App tách từng câu và chạy song song. Câu nào xong trước hiện lên trước.

## Đọc khung đáp án

| Bạn thấy | Nghĩa là |
| --- | --- |
| `ĐANG NHẬN DIỆN CÂU HỎI...` | Đang đọc nội dung, tách câu hỏi. |
| `Câu 31: RUNNING` | Câu đang chờ AI trả lời. |
| `Câu 31: RUNNING 12s (thử lại 2/4)` | Câu chạy lâu hơn 5 giây; đang thử lại lần 2. |
| `(kiểm tra lại ảnh)` | Đang hỏi AI lần hai để đối chiếu với ảnh gốc (bật bằng `IMAGE_VERIFICATION=1`). |
| `Đáp án đúng: B. ...` | Câu trắc nghiệm một đáp án. |
| `1-B, 2-A, 3-C` | Câu ghép thẻ hoặc nối cột. |
| `Đã hủy. Copy hoặc chụp câu mới.` | Bạn vừa bấm `H`. |
| `AI error: ...` | Lỗi mạng, hết thời gian hoặc bị giới hạn lượt gọi; xem [Khắc phục sự cố](#khắc-phục-sự-cố). |

Khung overlay kéo thả được. Đáp án tự ẩn sau `OVERLAY_DURATION_MS` (mặc định 14 giây); bấm `Left Shift` để hiện lại.

## Tài liệu local

Đặt giáo trình, slide, ghi chú vào thư mục `resources/` (hỗ trợ `.txt`, `.md`, `.pdf`, `.docx`), rồi chọn `Refresh resources` trong tray hoặc khởi động lại app. Khi trả lời, app tìm đoạn liên quan trong tài liệu này trước.

`resources/` bị Git ignore vì tài liệu có thể là dữ liệu riêng tư hoặc có bản quyền.

## Cấu hình

Mọi tuỳ chọn nằm trong `.env` (xem `.env.example` để biết đầy đủ):

| Biến | Mặc định | Tác dụng |
| --- | --- | --- |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | (bắt buộc) | Token và model của bạn. |
| `OPENAI_BASE_URL` | trống | Endpoint tương thích riêng. |
| `OPENAI_REASONING_EFFORT` | trống | Chỉ đặt nếu dịch vụ của bạn hỗ trợ. |
| `AUTO_START_MONITORING` | `0` | `1` = bật monitoring ngay khi mở app. |
| `IMAGE_VERIFICATION` | `1` | Hỏi AI lần hai bằng ảnh gốc: chính xác hơn nhưng chậm hơn. `0` để tắt. |
| `OVERLAY_DURATION_MS` | `14000` | Thời gian hiện đáp án. |
| `OVERLAY_FONT_POINT_SIZE` | `8` | Cỡ chữ overlay. |
| `OVERLAY_TEXT_ALPHA` | `100` | Độ rõ của chữ: 20 (rất mờ) đến 255 (rõ hết). |
| `PER_QUESTION_TIME_BUDGET_S` | `60` | Thời gian tối đa cho một câu, gồm cả thử lại. |
| `REQUEST_TIMEOUT_S` | `40` | Thời gian chờ một request mạng. |
| `MAX_PARALLEL_QUESTIONS` | `8` | Số câu chạy song song. Giảm nếu hay gặp lỗi 429. |
| `MAX_REQUESTS_PER_MINUTE` | `120` | Giới hạn request mỗi phút (`0` = không giới hạn). |
| `MAX_CLIPBOARD_CHARS` | `12000` | Cắt bớt văn bản quá dài trước khi gửi. |
| `MAX_RESPONSE_CHARS` | `480` | Độ dài tối đa đáp án hiển thị. |
| `ENABLE_WEB_FALLBACK` | `0` | `1` = cho phép tìm web khi tài liệu local không có. |

Trên Wayland, app tự chạy giao diện qua XWayland (`QT_QPA_PLATFORM=xcb`) để khung đáp án nổi trên màn hình thay vì thành một cửa sổ riêng. Đặt `QT_QPA_PLATFORM` thủ công nếu muốn ghi đè.

## Quyền riêng tư

- Khi monitoring bật, **mọi** text bạn copy và **mọi** ảnh chụp màn hình vào clipboard đều được gửi tới dịch vụ AI. **Tắt monitoring trước khi copy hoặc chụp nội dung riêng tư** (mật khẩu, tin nhắn, thông tin cá nhân).
- Đoạn trích từ `resources/` và kết quả web (nếu bật) cũng được gửi kèm.
- App lọc được một số mẫu secret rõ ràng trong **văn bản**, nhưng không lọc ảnh và không bảo vệ tuyệt đối.
- `.env`, `resources/`, trạng thái chạy và venv đều bị Git ignore. Nếu token từng bị lộ hoặc bị commit, hãy thu hồi token đó ngay tại nhà cung cấp.

## Khắc phục sự cố

| Hiện tượng | Cách xử lý |
| --- | --- |
| Copy/chụp mà không có gì xảy ra | Kiểm tra monitoring đã bật chưa (nhấp tray). Nếu một câu đang chạy, nội dung mới bị bỏ qua: bấm `H` rồi thử lại. |
| Báo trùng nhưng là câu mới | Bấm `H` trong vòng 60 giây để vẫn gửi. |
| Chụp màn hình không được gửi | Công cụ chụp phải **copy ảnh vào clipboard**, không chỉ lưu thành file. |
| Báo thiếu cấu hình | Kiểm tra `.env` có `OPENAI_API_KEY` và `OPENAI_MODEL`, rồi mở lại app. |
| Không thấy biểu tượng tray | Dùng desktop có system tray (GNOME cần extension AppIndicator). |
| `Left Shift` hoặc `H` không ăn | Xem dòng `[STARTUP] Global hotkeys unavailable: ...` trong terminal. Trên Wayland thường do chưa vào nhóm `input`, xem bước 3 phần Bắt đầu nhanh. |
| `AI error: ... giới hạn lượt gọi` (429) | Giảm `MAX_PARALLEL_QUESTIONS` hoặc `MAX_REQUESTS_PER_MINUTE`. |
| `AI error: ... hết thời gian chờ` | Kiểm tra mạng; tăng `PER_QUESTION_TIME_BUDGET_S` hoặc đặt `IMAGE_VERIFICATION=0` cho nhanh hơn. |
| `Missing virtual environment` khi chạy `./run.sh` | Làm lại bước 1 phần Bắt đầu nhanh. |

Log chi tiết (`[SKIP]`, `[CANCEL]`, `[RESULT]`, …) hiện trong terminal đã chạy `./run.sh`.

## Cấu trúc thư mục

```text
src/clip_overlay_ai/  Mã nguồn
tests/                Test tự động (pytest)
docs/                 Tài liệu kiến trúc
resources/            Tài liệu local của bạn (không commit)
.env.example          Mẫu cấu hình, không chứa secret
run.sh                Script chạy app
```
