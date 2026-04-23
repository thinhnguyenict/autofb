# Hướng dẫn setup và sử dụng tool trên VPS Ubuntu

## 1) Chuẩn bị VPS

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv ffmpeg libgl1 libglib2.0-0
```

## 2) Chuẩn bị source code

```bash
cd /home/ubuntu
# Nếu đã có source thì bỏ qua bước clone
git clone https://github.com/thinhnguyenict/autofb.git
cd /home/ubuntu/autofb
```

## 3) Tạo môi trường Python và cài thư viện

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r reqs.txt
```

## 4) Cấu hình

1. Tạo file cấu hình:

```bash
cp config.json.example config.json
```

2. Sửa `config.json` theo dữ liệu thật:
- `excel.path`: đường dẫn file dữ liệu bài post (ví dụ `./data.xlsx`)
- `excel.caption_file`: đường dẫn file caption
- `pages.page_id`: danh sách page_id
- `pages.access_token`: danh sách page access token (đúng thứ tự với page_id)
- `pages.page_name`: tên page (nếu dùng script ads)
- `pages.act_id`: tài khoản quảng cáo (nếu dùng script ads)

3. Chuẩn bị dữ liệu:
- Ảnh: thư mục `./img`
- Video: thư mục `./videos`
- File excel/caption theo cấu hình

## 5) Chạy thử thủ công

```bash
cd /home/ubuntu/autofb
source .venv/bin/activate
python3 create_fb_post.py
```

Một số lệnh chạy khác:

```bash
python3 create_ad_post.py          # chạy đăng ad post
python3 create_vid_reels_post.py   # chạy đăng reels theo video
```

## 6) Chạy nền bằng systemd (khuyến nghị)

Tạo service:

```bash
sudo nano /etc/systemd/system/autofb.service
```

Nội dung mẫu:

```ini
[Unit]
Description=AutoFB poster
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/autofb
Environment="PATH=/home/ubuntu/autofb/.venv/bin"
ExecStart=/home/ubuntu/autofb/.venv/bin/python /home/ubuntu/autofb/create_fb_post.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Kích hoạt service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable autofb
sudo systemctl start autofb
sudo systemctl status autofb
journalctl -u autofb -f
```

## 7) Chạy theo lịch bằng cron (tuỳ chọn)

Mở cron:

```bash
crontab -e
```

Ví dụ chạy mỗi ngày lúc 02:00, 06:00, 10:00:

```cron
0 2,6,10 * * * cd /home/ubuntu/autofb && /home/ubuntu/autofb/.venv/bin/python create_ad_post.py >> /home/ubuntu/autofb/create_ad_post.log 2>&1
```

## 8) Lưu ý vận hành

- Luôn chạy trong `.venv` để tránh lỗi thiếu package.
- Không commit `config.json` chứa token thật.
- Kiểm tra log định kỳ (`journalctl` hoặc file `.log`) để phát hiện token hết hạn/lỗi API.
