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
- [ ] DB và storage layer
- [ ] Fetcher (retry, rate limit, phát hiện bị chặn)
- [ ] Source adapter cho từng site
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
