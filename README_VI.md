# AutoFB – Hướng dẫn tiếng Việt

[English README](README.md)

AutoFB là công cụ hỗ trợ quản lý nội dung và đăng bài Facebook đang được chuyển
từ các script đơn lẻ sang ứng dụng đa người dùng. Phiên bản hiện tại có FastAPI,
workspace phân quyền, Meta OAuth, token mã hóa, lịch đăng bài, worker nền, lưu trữ
media local/S3 và các công cụ vận hành cho VPS.

> AutoFB không thay thế quy trình OAuth, App Review hoặc chính sách nền tảng của
> Meta. Không nhập hay lưu mật khẩu Facebook của người dùng vào ứng dụng.

## Mục lục

- [Yêu cầu bảo mật](#yêu-cầu-bảo-mật)
- [Cài VPS Ubuntu 2404 bằng một dòng lệnh](#cài-vps-ubuntu-2404-bằng-một-dòng-lệnh)
- [Các câu hỏi trong trình cài đặt](#các-câu-hỏi-trong-trình-cài-đặt)
- [Việc cần làm sau khi cài](#việc-cần-làm-sau-khi-cài)
- [Chạy bằng Docker ở máy local](#chạy-bằng-docker-ở-máy-local)
- [Cấu hình môi trường](#cấu-hình-môi-trường)
- [Kiến trúc và dịch vụ](#kiến-trúc-và-dịch-vụ)
- [Meta OAuth và kết nối Page](#meta-oauth-và-kết-nối-page)
- [Media local và S3MinIO](#media-local-và-s3minio)
- [Worker và lịch đăng bài](#worker-và-lịch-đăng-bài)
- [Backup và khôi phục](#backup-và-khôi-phục)
- [Kiểm tra trước khi chạy pilot](#kiểm-tra-trước-khi-chạy-pilot)
- [Lệnh phát triển và kiểm thử](#lệnh-phát-triển-và-kiểm-thử)
- [Giới hạn hiện tại](#giới-hạn-hiện-tại)

## Yêu cầu bảo mật

- Không commit `.env`, `config.json`, Facebook token, Meta App Secret, khóa Fernet,
  AWS key hoặc token của dịch vụ backup lên Git.
- Chỉ dùng `config.json.example` làm mẫu cho các script legacy.
- Nếu credential từng xuất hiện trong lịch sử Git, phải thu hồi và tạo credential
  mới; chỉ xóa file khỏi commit mới là chưa đủ.
- Ứng dụng chỉ lưu hash của session token. Token OAuth/Page được mã hóa bằng
  Fernet trước khi ghi vào database.
- Production phải dùng HTTPS, HSTS và domain công khai. Không nhúng token vào URL.
- Dùng Meta OAuth chính thức; tuyệt đối không yêu cầu mật khẩu Facebook.

## Cài VPS Ubuntu 24.04 bằng một dòng lệnh

### 1. Chuẩn bị

- VPS mới chạy **Ubuntu 24.04**.
- Đăng nhập bằng `root` hoặc mở root shell bằng `sudo -i`.
- Domain đã trỏ bản ghi DNS về IP của VPS.
- Repository Git chứa source AutoFB.

### 2. Chạy một dòng lệnh

Thay `YOUR_ORG` và `YOUR_REPO` bằng tài khoản/tổ chức và repository GitHub của
bạn:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/YOUR_ORG/YOUR_REPO/main/deploy/install_ubuntu_24_04.sh)"
```

Phải dùng dạng `bash -c "$(curl ...)"`, không dùng `curl ... | bash`. Trình cài
đọc câu trả lời trực tiếp từ terminal; pipe thẳng vào Bash có thể chiếm mất stdin.

File thực thi là [`deploy/install_ubuntu_24_04.sh`](deploy/install_ubuntu_24_04.sh).
Nó kiểm tra quyền root, xác nhận đúng Ubuntu 24.04, thu thập cấu hình rồi chuyển
cho installer aaPanel/Docker chính.

## Các câu hỏi trong trình cài đặt

Trình cài đặt sẽ hỏi:

1. **Domain ứng dụng** – chỉ nhập hostname, ví dụ `tool.example.com`, không nhập
   `https://`.
2. **Git repository URL** – HTTPS hoặc SSH. Không nhúng username/password/token
   vào URL; repository private nên dùng SSH deploy key.
3. **Thư mục cài đặt** – mặc định `/www/wwwroot/<domain>`.
4. **Local API port** – mặc định `8001`, dùng cho reverse proxy nội bộ.
5. **Có cài aaPanel không** – chọn `y` nếu VPS chưa có và bạn muốn installer cài.
6. **Meta App ID/App Secret** – có thể bỏ trống rồi cấu hình sau trong `.env`.
7. **Admin đầu tiên** – email, mật khẩu tối thiểu 12 ký tự và tên workspace; có
   thể bỏ trống để tạo tài khoản sau.

Meta App Secret và mật khẩu admin được nhập ở chế độ ẩn, không xuất hiện trong
màn hình xác nhận.

Installer sẽ:

- cài Git, Docker và Docker Compose;
- clone repository vào thư mục đã chọn;
- tạo `.env` permission `600`;
- tạo `docker-compose.override.yml` chỉ bind API vào `127.0.0.1`;
- chạy API và worker;
- chạy backup container nếu đã cấu hình off-site backup;
- in thông tin reverse proxy cần nhập trong aaPanel.

## Việc cần làm sau khi cài

### Reverse proxy và SSL

Trong aaPanel:

1. Tạo website cho domain.
2. Tạo Reverse Proxy về `http://127.0.0.1:8001` hoặc port installer đã chọn.
3. Cấp Let's Encrypt certificate.
4. Bật Force HTTPS.
5. Giữ `AUTOFB_ENABLE_HSTS=1` sau khi HTTPS hoạt động chính xác.

### Hoàn thiện `.env`

```bash
cd /www/wwwroot/DOMAIN_CUA_BAN
nano .env
```

Ít nhất cần hoàn thiện Meta OAuth, URL cảnh báo, off-site backup và tùy chọn S3.
Sau khi sửa:

```bash
docker compose --profile backup up -d --build autofb-api autofb-worker autofb-backup
```

### Kiểm tra container

```bash
docker compose ps
docker compose logs --tail=200 autofb-api
docker compose logs --tail=200 autofb-worker
docker compose logs --tail=200 autofb-backup
```

## Chạy bằng Docker ở máy local

```bash
cp config.json.example config.json
# Chỉ chỉnh config.json ở local, không commit.
docker compose up -d --build autofb-api autofb-worker
```

Địa chỉ thường dùng:

- Dashboard/API: <http://127.0.0.1:8001>
- OpenAPI docs: <http://127.0.0.1:8001/docs>
- Liveness: <http://127.0.0.1:8001/healthz>
- Readiness: <http://127.0.0.1:8001/readyz>
- Worker readiness: <http://127.0.0.1:8001/workerz>
- Backup readiness: <http://127.0.0.1:8001/backupz>

Dashboard legacy nằm trong Compose profile `legacy` và không tự chạy cùng API mới.

## Cấu hình môi trường

### Ứng dụng và Meta

| Biến | Ý nghĩa |
| --- | --- |
| `AUTOFB_PUBLIC_URL` | Origin HTTPS công khai, ví dụ `https://tool.example.com` |
| `AUTOFB_ENABLE_HSTS` | Đặt `1` ở production sau khi HTTPS hoạt động |
| `AUTOFB_DATABASE_PATH` | Đường dẫn SQLite, mặc định `autofb.db` |
| `AUTOFB_TOKEN_ENCRYPTION_KEY` | Fernet key dùng mã hóa OAuth/Page token |
| `META_APP_ID` | Meta App ID |
| `META_APP_SECRET` | Meta App Secret |
| `META_REDIRECT_URI` | OAuth callback cùng host với `AUTOFB_PUBLIC_URL` |

Tạo Fernet key:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

### Worker

| Biến | Mặc định | Ý nghĩa |
| --- | ---: | --- |
| `AUTOFB_WORKER_POLL_SECONDS` | `30` | Chu kỳ kiểm tra job |
| `AUTOFB_WORKER_BATCH_SIZE` | `10` | Số job tối đa mỗi lần claim, từ 1–100 |
| `AUTOFB_WORKER_MIN_PUBLISH_INTERVAL_SECONDS` | `1` | Khoảng nghỉ giữa các lần gửi, từ 0–60 giây |
| `AUTOFB_WORKER_MAX_HEARTBEAT_AGE` | `300` | Tuổi heartbeat tối đa trước khi worker bị coi là stale |

### Cảnh báo

| Biến | Ý nghĩa |
| --- | --- |
| `AUTOFB_BACKUP_ALERT_URL` | HTTPS webhook khi backup thất bại |
| `AUTOFB_BACKUP_ALERT_TOKEN` | Bearer token tùy chọn cho webhook backup |
| `AUTOFB_ERROR_WEBHOOK_URL` | HTTPS webhook cho exception API chưa xử lý |
| `AUTOFB_ERROR_WEBHOOK_TOKEN` | Bearer token tùy chọn cho error webhook |

Payload cảnh báo không chứa request body, query string, exception message, backup
destination hoặc secret.

## Kiến trúc và dịch vụ

```text
Browser dashboard
       |
       v
FastAPI API ---- SQLite (single-VPS MVP)
    |   |\
    |   | +---- encrypted Meta/Page tokens
    |   +------ local volume hoặc S3/MinIO
    +---------- publish_jobs
                    |
                    v
              PublishWorker ---- Meta Graph API
```

Các Compose service chính:

- `autofb-api`: API, dashboard, auth, workspace và nội dung.
- `autofb-worker`: claim job, publish, retry và ghi kết quả.
- `autofb-backup`: backup SQLite, restore drill và upload off-site.
- `autofb`: dashboard legacy, chỉ chạy khi bật profile `legacy`.

Role trong workspace gồm `owner`, `admin`, `editor`, `publisher`, `viewer`.

## Meta OAuth và kết nối Page

Quy trình production:

1. Tạo Meta app và khai báo callback đúng `META_REDIRECT_URI`.
2. Hoàn tất permission/App Review cần thiết.
3. Đăng nhập AutoFB, tạo workspace.
4. Kết nối Facebook bằng OAuth.
5. Import các Page được tài khoản cho phép quản lý.
6. Chạy live connection diagnostic từ dashboard.

Diagnostic gần nhất phải `valid`, không quá 24 giờ và connection chưa hết hạn thì
production preflight mới pass. Token chỉ được giải mã tạm thời trong memory và
không trả về browser.

## Media local và S3/MinIO

Mặc định:

```text
AUTOFB_MEDIA_BACKEND=local
AUTOFB_MEDIA_DIR=/var/lib/autofb/media
AUTOFB_MEDIA_MAX_BYTES=104857600
```

Dùng S3/MinIO:

```text
AUTOFB_MEDIA_BACKEND=s3
AUTOFB_S3_BUCKET=autofb-media
AUTOFB_S3_PREFIX=autofb-media
AUTOFB_S3_ENDPOINT_URL=https://minio.example.com
AUTOFB_S3_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

Với AWS S3 thật có thể bỏ `AUTOFB_S3_ENDPOINT_URL`. Media được kiểm tra dung lượng,
chuẩn hóa filename và giới hạn theo workspace/bucket/prefix.

Di chuyển dữ liệu local lên S3:

```bash
make migrate-media-s3 DRY_RUN=1
make migrate-media-s3
# Chỉ xóa source sau khi backup và xác minh:
make migrate-media-s3 DELETE_LOCAL=1
```

## Worker và lịch đăng bài

Worker thực hiện:

- claim có điều kiện để tránh hai worker xử lý cùng job;
- giới hạn batch và pacing giữa các publish;
- ghi `publish_results` cho từng attempt;
- retry lỗi tạm thời theo exponential backoff;
- tôn trọng header Meta `Retry-After` khi HTTP 429;
- phục hồi job `running` bị stale;
- gửi heartbeat cho `/workerz`.

Chạy một vòng worker thủ công:

```bash
make worker-once
```

## Backup và khôi phục

Backup local nhất quán:

```bash
make backup-db
```

Backup off-site yêu cầu URL có `{filename}`:

```bash
AUTOFB_OFFSITE_BACKUP_URL='https://backup.example/autofb/{filename}' \
AUTOFB_OFFSITE_BACKUP_TOKEN='TOKEN' \
make backup-offsite
```

Mỗi off-site backup được kiểm tra integrity, restore thử vào thư mục tạm, tính
SHA-256 rồi mới upload. Backup gần nhất phải thành công trong vòng 48 giờ để
`/backupz` và preflight pass.

Restore drill không phá dữ liệu:

```bash
make restore-drill BACKUP=backups/autofb-YYYYMMDDTHHMMSSZ.db
```

Khôi phục database:

```bash
# Dừng API và worker trước.
make restore-db BACKUP=backups/autofb-YYYYMMDDTHHMMSSZ.db
# Ghi đè database hiện có và giữ safety copy:
make restore-db BACKUP=backups/autofb-YYYYMMDDTHHMMSSZ.db FORCE=1
```

Xoay Fernet key:

```bash
AUTOFB_OLD_TOKEN_ENCRYPTION_KEY='OLD_KEY' \
AUTOFB_NEW_TOKEN_ENCRYPTION_KEY='NEW_KEY' \
make rotate-token-key
```

## Kiểm tra trước khi chạy pilot

Trong API container hoặc môi trường có đầy đủ `.env`:

```bash
make preflight
```

Preflight kiểm tra:

- Meta config, HTTPS public origin, callback host và HSTS;
- Fernet key;
- database integrity, foreign keys và schema;
- admin account;
- media local hoặc S3 bucket;
- worker heartbeat;
- off-site backup gần nhất;
- Meta connection, imported Page và live diagnostic trong 24 giờ;
- backup/error alert receiver.

Sau khi deploy:

```bash
make pilot-acceptance URL=https://tool.example.com
```

Lệnh này kiểm tra `/healthz`, `/readyz`, `/workerz`, `/backupz` từ bên ngoài và
không in URL/response body/secret vào báo cáo.

## Lệnh phát triển và kiểm thử

```bash
# Cài dependency và Playwright Chromium
make bootstrap

# Chạy unit test
make test

# Test + compile + shell syntax + whitespace + smoke
make check

# FastAPI smoke
make smoke

# Chụp dashboard
make screenshot

# Tạo admin đầu tiên
AUTOFB_ADMIN_EMAIL=admin@example.com \
AUTOFB_ADMIN_PASSWORD='mat-khau-rat-manh' \
AUTOFB_ADMIN_WORKSPACE='Main' \
make create-admin

# Preview/dọn dữ liệu vận hành hết hạn
make cleanup-db DRY_RUN=1
make cleanup-db
```

CI tại `.github/workflows/test.yml` chạy `make check`, cài Playwright Chromium,
chạy FastAPI smoke và xác minh screenshot PNG.

## Cấu hình legacy

Các script cũ vẫn đọc `config.json` thông qua `autofb.config.load_config()`.
Danh sách Page ID và Page token phải có cùng số phần tử. Page name là bắt buộc với
workflow quảng cáo legacy. Config sai sẽ dừng trước khi gửi request tới provider.

```bash
cp config.json.example config.json
# Điền config tại local, tuyệt đối không commit config.json.
```

## Giới hạn hiện tại

Phiên bản hiện tại phù hợp cho controlled single-VPS pilot sau khi tất cả preflight
và acceptance gate đều pass. Đây chưa phải kiến trúc horizontal scaling cuối cùng.

Các hạng mục tiếp theo:

- chuyển SQLite sang PostgreSQL;
- dùng Redis/shared queue;
- distributed worker lease và rate limiting;
- provider-supported idempotency;
- Meta production App Review;
- load test và external security review.

Xem roadmap chi tiết tại [`docs/product-roadmap.md`](docs/product-roadmap.md).

## Giấy phép và trách nhiệm vận hành

Chỉ sử dụng AutoFB với Page, tài khoản và nội dung mà bạn có quyền quản lý. Người
vận hành chịu trách nhiệm tuân thủ điều khoản Meta, bảo vệ dữ liệu người dùng,
quản lý credential, backup, retention và quy định pháp luật tại khu vực triển khai.
