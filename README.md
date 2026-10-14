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
make test   # pytest + vitest
make lint   # ruff + tsc
```

## Roadmap

- [x] Scaffold backend + frontend
- [x] DB và storage layer
- [x] Fetcher (retry, rate limit, phát hiện bị chặn)
- [x] Source adapter cho từng site (đang có: truyenhoan, truyendich)
- [x] Crawl pipeline có resume
- [x] Xuất TXT / JSON / EPUB
- [x] UI quản lý crawl và thư viện
- [x] Playwright cho site Cloudflare (xem phần giới hạn bên dưới)
- [x] Adapter site Trung (đang có: uukanshu, czbooks)
- [ ] Dịch raw Trung sang Việt
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

## Crawl một truyện

Qua CLI, chạy ngay ở foreground:

```bash
cd backend
../.venv/bin/python -m app.cli crawl download "<url truyện>"
../.venv/bin/python -m app.cli jobs            # xem job gần đây
```

Qua API, chạy nền trong server:

```bash
# tạo job
curl -X POST http://127.0.0.1:8000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"url":"<url truyện>"}'

# theo tiến độ (SSE: event snapshot đầu tiên, rồi progress từng chương)
curl -N http://127.0.0.1:8000/api/jobs/1/events

# tạm dừng / chạy lại / huỷ
curl -X POST http://127.0.0.1:8000/api/jobs/1/pause
curl -X POST http://127.0.0.1:8000/api/jobs/1/resume
curl -X POST http://127.0.0.1:8000/api/jobs/1/cancel

# tải chương mới của truyện đã có
curl -X POST http://127.0.0.1:8000/api/novels/1/update
```

Ngắt giữa chừng không mất gì. Chương đã có trên đĩa thì lần chạy sau bỏ qua,
và job còn dở sẽ được tự đưa lại vào hàng đợi khi server khởi động lại.
Chương VIP được ghi là `skipped_vip` chứ không tính là lỗi, chương lỗi sẽ
retry tới giới hạn `CRAWLW_CHAPTER_RETRY_LIMIT`.

Tốc độ crawl bị giới hạn có chủ đích (`CRAWLW_PER_DOMAIN_DELAY`, mặc định
0.6s mỗi request và 4 request song song mỗi host), nên truyện vài trăm chương
sẽ mất vài phút. Đừng tăng lên quá cao nếu không muốn bị site chặn.

## Xuất file để đọc

```bash
cd backend
../.venv/bin/python -m app.cli export 1 --format epub
../.venv/bin/python -m app.cli export 1 --format txt
../.venv/bin/python -m app.cli export 1 --format json
../.venv/bin/python -m app.cli export 1 --format epub --volume-size 500
```

Qua API:

```bash
curl -OJ "http://127.0.0.1:8000/api/novels/1/export?format=epub"
curl -OJ "http://127.0.0.1:8000/api/novels/1/export?format=epub&volume_size=500"
curl -OJ "http://127.0.0.1:8000/api/novels/1/export?format=txt&translated=true"
```

File nằm trong `data/exports/`.

- **EPUB** có mục lục, metadata (tác giả, thể loại, nguồn) và ảnh bìa nếu
  crawl đã tải được. Đây là định dạng nên dùng để đọc trên điện thoại hay
  máy đọc sách.
- **TXT** một file duy nhất, mở được ở mọi nơi.
- **JSON** để xử lý tiếp bằng script.

Truyện tải dở vẫn xuất được, chỉ gồm những chương đã có. Truyện quá dài thì
dùng `--volume-size`: file sẽ được chia thành nhiều phần và gói trong một
`.zip`, vì một EPUB vài nghìn chương mở rất chậm trên điện thoại và có app
đọc sách bỏ luôn không mở.

Thêm `translated=true` để xuất bản dịch; chương nào chưa dịch thì tự lấy bản
gốc, nên sách vẫn liền mạch.

## Tình hình các site truyện Việt

Khảo sát trực tiếp (tháng 10/2026), gần 50 domain. Kết quả không vui:

| Site | Tình trạng |
| --- | --- |
| truyenhoan.com (cũ: truyenfull.tv) | **chạy được**, đã có adapter |
| truyendich.vn | **chạy được**, đã có adapter |
| truyencv.com | đóng cửa, trang chỉ còn chữ "Tạm biệt!" |
| metruyencv.net | đóng cửa, cùng thông báo như trên |
| metruyencv.com | sống nhưng Cloudflare chặn, cần Playwright |
| bachngocsach.cc | "BNS Reader ngừng hoạt động" |
| truyenchu.com.vn | sống, danh sách chương **có** trong HTML nhưng không phải thẻ `<a href>` nên cần parse riêng |
| webtruyen.com, truyenviet.vn | sống, chưa khảo sát xong cấu trúc |
| nhattruyen.com | domain đang được bán |
| 4vn.eu, hoasontrang.us | domain đã đổi sang mục đích khác |
| tangthuvien.net/.vn, truyenfull.vn/.io/.vip, wikidich.*, truyenyy.*, sstruyen.*, dtruyen.com, và ~20 domain khác | không kết nối được |

Nên đừng ngạc nhiên nếu một site hôm nay chạy mai lại chết. Domain nằm trong
`domains` của từng adapter nên đổi domain chỉ cần sửa một dòng. Dò nhanh bằng:

```bash
cd backend
../.venv/bin/python -m app.cli fetch "https://site.example/" --head 0
```

Hai site cùng dùng chung template (họ "truyenfull") nên phần đọc HTML nằm ở
`app/sources/vi_truyenfull.py`, mỗi adapter chỉ khai báo dạng URL riêng. Thêm
một site cùng họ chỉ mất khoảng 20 dòng.

## Trình duyệt nền và site bị chặn

Một số site trả về trang kiểm tra JavaScript thay vì nội dung. Request thường
không thể vượt qua, nên có thêm fetcher chạy Chromium ẩn.

Cài thêm (không bắt buộc, chỉ cần khi gặp site như vậy):

```bash
uv pip install --python .venv/bin/python -e './backend[browser]'
.venv/bin/python -m playwright install chromium
```

Thử một URL:

```bash
cd backend
../.venv/bin/python -m app.cli fetch "<url>" --head 0            # http thường
../.venv/bin/python -m app.cli fetch "<url>" --browser --head 0  # Chromium
../.venv/bin/python -m app.cli fetch "<url>" --smart --head 0    # http, chặn thì chuyển browser
```

Khi crawl, hệ thống tự chọn: site nào adapter đã khai `needs_browser` thì dùng
Chromium luôn, còn lại thử HTTP trước. Nếu HTTP bị chặn mà browser vào được thì
host đó được ghi nhớ, các chương sau khỏi phải thử HTTP rồi bị chặn lại. Browser
đắt hơn HTTP khoảng trăm lần nên chỉ dùng khi cần.

### Giới hạn thật, đã kiểm tra

**Chromium ẩn không vượt được Cloudflare.** Thử trên metruyencv.com: browser chờ
hết 25 giây mà trang kiểm tra vẫn không chịu qua. Cloudflare nhận ra đây là
trình duyệt tự động. Đây không phải lỗi cấu hình, và tool này không đi theo
hướng cố né cơ chế chống bot.

Cách dùng được cho những site đó là **dán cookie từ trình duyệt của chính bạn**:
mở site bằng Chrome/Firefox như bình thường, qua được trang kiểm tra, rồi copy
cookie trong DevTools (Network → chọn một request → Request Headers → Cookie) và
dán vào trang **Cài đặt**. Cookie được dùng cho cả HTTP lẫn browser. Cookie
Cloudflare thường sống vài ngày nên sẽ phải dán lại.

Trình duyệt nền vẫn hữu ích cho site chỉ render nội dung bằng JavaScript —
trường hợp này nó hoạt động tốt và có test chứng minh.

## Cài đặt trong app

Trang **Cài đặt** lưu vào database nên đổi là có hiệu lực ngay, không cần
restart:

- **Proxy** cho site bị chặn theo vùng.
- **Giãn cách và số request song song** mỗi site. Hạ giãn cách xuống thì nhanh
  hơn nhưng dễ bị chặn.
- **Timeout** và **số lần thử lại mỗi chương**.
- **Bật/tắt trình duyệt nền**, kèm nút kiểm tra xem Chromium đã cài chưa.
- **Cookie theo từng site**.
- **API key** cho engine dịch bằng LLM. Key chỉ được lưu ở máy bạn và không bao
  giờ trả về qua API — trang cài đặt chỉ hiện 4 ký tự cuối để phân biệt.

## Tình hình các site truyện Trung

Khảo sát trực tiếp 20 domain:

| Site | Tình trạng |
| --- | --- |
| uukanshu.cc (UU看書) | **chạy được**, đã có adapter, phồn thể |
| czbooks.net (小說狂人) | **chạy được**, đã có adapter, phồn thể |
| 69shuba.com, 81zw.com, twkan.com | Cloudflare chặn (trang "Just a moment...") |
| ptwxz.com (飄天文學) | có trang chống bot, nội dung GB18030 |
| 3bqg.cc (笔趣阁) | redirect sang 33bqg.com rồi đẩy vào `/user/verify.html` |
| xbanxia.cc, shu05.com, ciweimao.com | sống, chưa khảo sát cấu trúc |
| biquge.com, biqugee.com, xbiquge.la, uukanshu.net, b5200.net, 23us.com, trxs.cc, dxmwx.org, bxwxorg.com | không kết nối được |

Site Trung khác site Việt ở hai điểm, và đó là lý do có `app/sources/zh_base.py`
riêng:

- **URL chương là ID database** (`/book/27265/17948862.html`), không chứa số
  chương. Nên số chương được lấy từ tiêu đề (`第12章`, kể cả số viết bằng chữ
  như `第十二章` hay `第一百零八回`). Chương không có số trong tiêu đề (`新書感言`)
  được xếp vào khe trống ngay trước chương kế tiếp, nên lời mở đầu thành chương
  0 đúng như cách site tự đánh số.
- **Danh sách chương nằm trên một trang**, không phân trang, và chương mới nhất
  thường được nhắc lại ở đầu trang nên phải loại trùng.

Chữ phồn thể và giản thể được xử lý trong `app/sources/zh_text.py`
(`to_simplified`, `to_traditional`, `looks_traditional`). Cùng một truyện hay
được đăng ở cả hai dạng, mà glossary tên riêng xây từ dạng này sẽ không khớp
dạng kia, nên bước dịch sẽ chuẩn hoá về một dạng trước.

Encoding: nhiều site Trung khai GBK/GB2312 chỉ trong thẻ `<meta>` chứ không
trong HTTP header, nên `app/fetch/decode.py` ưu tiên meta hơn header và nới
gb2312/gbk thành gb18030.
