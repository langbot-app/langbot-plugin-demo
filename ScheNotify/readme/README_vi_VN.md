# ScheNotify

Lên lịch thông báo bằng ngôn ngữ tự nhiên

## Tính năng

ScheNotify là một plugin LangBot cho phép người dùng thiết lập các lời nhắc theo thời gian thông qua tương tác bằng ngôn ngữ tự nhiên với LLM.

### Các tính năng chính

- **Tương tác bằng ngôn ngữ tự nhiên**: Hiểu ý định lên lịch của người dùng thông qua LLM
- **Phân tích thời gian thông minh**: Tự động lấy thời gian hiện tại và tính toán thời gian nhắc nhở
- **Hỗ trợ đa ngôn ngữ**: Hỗ trợ tin nhắn nhắc nhở bằng tiếng Trung và tiếng Anh
- **Lệnh quản lý lịch trình**: Xem và xóa các lời nhắc đã lên lịch
- **Thông báo tự động**: Tự động gửi tin nhắn nhắc nhở vào thời gian đã lên lịch

## Cấu hình

### Cài đặt ngôn ngữ

Bạn có thể chọn ngôn ngữ cho các tin nhắn nhắc nhở trong cấu hình plugin:

- `zh_Hans` (Tiếng Trung giản thể) - Mặc định
- `en_US` (Tiếng Anh)

## Cách sử dụng

### 1. Lên lịch qua LLM

Chỉ cần nói với LLM lịch trình của bạn bằng ngôn ngữ tự nhiên:

**Ví dụ:**
```
Nhắc tôi có cuộc họp vào 3 giờ chiều mai
Nhắc tôi gửi báo cáo vào 9 giờ sáng ngày kia
Nhắc tôi ăn trưa vào 12 giờ trưa thứ Hai tới
Nhắc tôi về bữa tối Giáng sinh lúc 2024-12-25 18:00
```

LLM sẽ tự động:
1. Gọi `get_current_time_str` để lấy thời gian hiện tại
2. Phân tích cách diễn đạt thời gian của bạn và chuyển đổi sang định dạng chuẩn
3. Gọi `schedule_notify` để tạo lời nhắc

### 2. Xem các lời nhắc đã lên lịch

Sử dụng lệnh để xem tất cả các lời nhắc đã lên lịch:

```
!sche
```

Ví dụ đầu ra:
```
[Notify] Các lời nhắc đã lên lịch:
#1 2024-12-25 18:00:00: Bữa tối Giáng sinh
#2 2024-12-26 09:00:00: Gửi báo cáo
```

### 3. Xóa lời nhắc

Sử dụng lệnh để xóa một lời nhắc cụ thể (sử dụng số từ `!sche`):

```
!dsche i <số>
```

Ví dụ:
```
!dsche i 1   # Xóa lời nhắc thứ nhất
```

## Các thành phần

### Công cụ

1. **get_current_time_str** - Lấy thời gian hiện tại
   - Định dạng trả về: `YYYY-MM-DD HH:MM:SS`
   - LLM phải gọi công cụ này trước khi thiết lập lời nhắc

2. **schedule_notify** - Lên lịch thông báo
   - Tham số: chuỗi thời gian, tin nhắn nhắc nhở
   - Tự động lấy thông tin phiên từ tham số session của Công cụ

### Lệnh

1. **sche** (viết tắt: s) - Liệt kê tất cả các lời nhắc đã lên lịch
2. **dsche** (viết tắt: d) - Xóa lời nhắc được chỉ định

## Chi tiết kỹ thuật

- Khoảng thời gian kiểm tra: Mỗi 60 giây
- Độ chính xác thời gian: Cấp độ phút (kiểm tra mỗi phút)
- Thông tin phiên: Được lấy tự động thông qua tham số session của Công cụ
- Lưu trữ: Hiện đang sử dụng bộ nhớ trong (mất đi khi khởi động lại)

## Ví dụ hội thoại

**Người dùng:** Nhắc tôi tham gia cuộc họp vào 2 giờ chiều mai

**LLM:** Chắc chắn rồi, tôi sẽ đặt lời nhắc cho bạn.

*[LLM gọi get_current_time_str]*
*[LLM gọi schedule_notify(time_str="2024-12-26 14:00:00", message="Tham gia cuộc họp")]*

**LLM:** Xong! Tôi sẽ nhắc bạn vào lúc 2024-12-26 14:00:00: Tham gia cuộc họp

*[Ngày hôm sau lúc 2 giờ chiều]*

**Bot:** [Notify] Tham gia cuộc họp

## Ghi chú

- Thời gian nhắc nhở phải ở tương lai, thời gian trong quá khứ sẽ bị từ chối
- Tin nhắn nhắc nhở sẽ được gửi đến cùng một phiên nơi lời nhắc được thiết lập
- Các lời nhắc chưa gửi sẽ bị mất sau khi khởi động lại plugin (tính năng lưu trữ lâu dài sẽ được hỗ trợ trong các phiên bản tương lai)

## Thông tin nhà phát triển

- Tác giả: RockChinQ
- Phiên bản: 0.2.0
- Loại plugin: LangBot Plugin v1

## Giấy phép

Một phần của hệ sinh thái plugin LangBot.
