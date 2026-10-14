# crawl_writer

Tool crawl truyện chữ từ các sàn truyện Việt (bản convert) và Trung (raw) về máy để đọc offline.

Backend FastAPI, frontend React/Vite. API-first nên sau này viết app mobile thì dùng lại nguyên bộ endpoint.

## Trạng thái

Đang phát triển. Xem phần Roadmap ở dưới.

## Yêu cầu

- Python 3.11+ (dev dùng 3.13)
- Node 20+
- [uv](https://docs.astral.sh/uv/) để quản lý venv

## Cài đặt

```bash
make setup
```

Lệnh này tạo `.venv`, cài backend ở chế độ editable kèm dev deps, rồi `npm install` cho frontend.

## Chạy

Hai dev server chạy ở hai terminal:

```bash
make dev-api   # FastAPI trên :8000
make dev-web   # Vite trên :5173
```

Mở http://localhost:5173. Vite proxy `/api` sang backend nên frontend chỉ dùng URL tương đối.

API docs: http://localhost:8000/docs

## Cấu hình

Copy `.env.example` thành `.env` rồi điền những gì cần. Tất cả đều không bắt buộc. Biến môi trường dùng tiền tố `CRAWLW_`.

Dữ liệu mặc định nằm trong `data/`:

```
data/
  crawlw.db          # metadata: truyện, chương, job, settings
  novels/<id>/       # nội dung chương dạng .txt
  exports/           # file EPUB/TXT/JSON đã xuất
```

## Kiểm tra

```bash
make test   # pytest
make lint   # ruff + tsc
```

## Roadmap

- [x] Scaffold backend + frontend
- [x] DB và storage layer
- [x] Fetcher (retry, rate limit, phát hiện bị chặn)
- [x] Source adapter cho từng site (đang có: truyenhoan)
- [ ] Crawl pipeline có resume
- [ ] Xuất TXT / JSON / EPUB
- [ ] UI quản lý crawl và thư viện
- [ ] Playwright cho site Cloudflare
- [ ] Adapter site Trung + dịch sang Việt
- [ ] Trình đọc trong web
- [ ] Theo dõi và tự cập nhật chương mới

## Lưu ý pháp lý

Tool này dành cho việc **backup cá nhân** nội dung bạn có quyền truy cập hợp pháp. Truyện trên các site đều thuộc bản quyền của tác giả và nhà phát hành. Đừng phân phối lại hay bán nội dung tải về. Hãy để nguyên rate limit mặc định để không làm quá tải site nguồn.

Kiến trúc adapter tham khảo cách tiếp cận của [lightnovel-crawler](https://github.com/lncrawl/lightnovel-crawler) (mỗi site một crawler cùng chung một contract, resume theo chương, phân biệt bị chặn với lỗi mạng). Code trong repo này viết riêng.

## Migration

Schema do Alembic quản lý:

```bash
cd backend
../.venv/bin/python -m alembic upgrade head          # áp dụng migration
../.venv/bin/python -m alembic revision --autogenerate -m "mô tả"
../.venv/bin/python -m alembic check                 # kiểm tra model có lệch schema không
```

## CLI

```bash
cd backend
../.venv/bin/python -m app.cli paths                 # xem dữ liệu nằm ở đâu
../.venv/bin/python -m app.cli db init               # tạo bảng
../.venv/bin/python -m app.cli db seed-demo          # tạo một truyện giả để thử API
```

## Thêm một site mới

Mỗi site là một adapter trong `backend/app/sources/`, cùng chung một contract
(`Source` trong `app/sources/base.py`). Các bước:

1. Dò xem site có truy cập được không:

   ```bash
   cd backend
   ../.venv/bin/python -m app.cli fetch "https://site.example/" --head 0
   ```

   Nếu báo `BLOCKED` thì đánh dấu `needs_browser = True` trên adapter.

2. Viết adapter, khai báo `key`, `name`, `domains`, `lang`, rồi thêm
   `@register`. Import nó trong `app/sources/__init__.py` để decorator chạy.

3. Thêm fixture trong `backend/tests/fixtures/<key>/`: dựng lại **cấu trúc**
   markup của site (tag, class, id, dạng URL) nhưng dùng nội dung tự viết.
   Đừng commit nội dung truyện thật vào repo.

4. Kiểm tra bằng CLI:

   ```bash
   ../.venv/bin/python -m app.cli sources
   ../.venv/bin/python -m app.cli crawl info     "<url truyện>"
   ../.venv/bin/python -m app.cli crawl chapters "<url truyện>" --show 3
   ../.venv/bin/python -m app.cli crawl chapter  "<url chương>" --head 300
   ../.venv/bin/python -m app.cli crawl search   "tên truyện"
   ```

CLI phân biệt rõ nguyên nhân lỗi: `BLOCKED` là site chặn (cần browser, proxy
hoặc cookie), `LAYOUT` là markup đổi nên selector cần sửa, `FAILED` là lỗi
mạng.
