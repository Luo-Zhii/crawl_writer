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

API docs (OpenAPI 3.1.0): http://localhost:8000/docs

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
- [x] Adapter site Trung (đang có: uukanshu, czbooks, qidian)
- [x] Dịch raw Trung sang Việt + glossary (xem phần giới hạn bên dưới)
- [x] Trình đọc trong web
- [x] Theo dõi và tự cập nhật chương mới
- [x] Qidian: chương miễn phí (xem phần giới hạn bên dưới)

## Performance

Với 5000 chương (tối đa thử nghiệm), backend chạy trên SQLite local:

| Thao tác | Thời gian | Dung lượng |
| --- | --- | --- |
| `GET /api/novels/{id}` (chi tiết) | 92 ms | - |
| `GET /api/novels/{id}/chapters?limit=2000` | 104 ms | - |
| `POST /api/novels/{id}/export?format=txt` | 669 ms | 0.74 MB |
| `POST /api/novels/{id}/export?format=epub&volume_size=500` | 3.6 s | 0.47 MB (zip) |

Tốc độ crawl: bị giới hạn có chủ đích ở mức `CRAWLW_PER_DOMAIN_DELAY` (mặc định 0.6s/request, 4 request song song mỗi host). Truyện vài trăm chương sẽ mất vài phút tùy site.

## Demo

Sau khi chạy `make setup`, mở hai terminal:

```bash
# Terminal 1: backend
make dev-api

# Terminal 2: frontend
make dev-web
```

Rồi mở http://localhost:5173 và:

1. **Library** → bấm **Thêm truyện** để crawl từ một site
2. Nhập URL từ một trong 5 site sẵn sàng (xem phần trên)
3. Theo dõi tiến độ ở tab **Jobs**
4. Chọn truyện trong **Library** để xem, dịch, hoặc xuất file
5. **Cài đặt** để bật browser cho site Cloudflare, điều chỉnh delay, đăng nhập Google Translate/LLM

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

Khảo sát trực tiếp (tháng 10/2026), gần 50 domain. Các site **đang chạy được**:

| Site | Tình trạng |
| --- | --- |
| **truyenhoan.com** | ✓ chạy được, adapter sẵn sàng |
| **truyendich.vn** | ✓ chạy được, adapter sẵn sàng |

**Các site đã chết hoặc không sử dụng được:**

| Site | Tình trạng |
| --- | --- |
| truyencv.com, metruyencv.net | đóng cửa (thông báo "Tạm biệt!") |
| metruyencv.com | Cloudflare chặn, yêu cầu Playwright |
| bachngocsach.cc, nhattruyen.com | BNS Reader ngừng, domain đang bán |
| tangthuvien.net/.vn, truyenfull.vn/.io/.vip, wikidich.*, truyenyy.*, và ~30 domain | không kết nối được |

**Lưu ý:** Domain trong code dễ thay đổi (được khai báo trong `domains` của từng
adapter). Nếu một site bị chết có thể thử dò nhanh:

```bash
cd backend
../.venv/bin/python -m app.cli fetch "https://site.example/" --head 0
```

Hai site trên cùng template `app/sources/vi_truyenfull.py`, mỗi adapter chỉ khai
báo URL pattern riêng.

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

Khảo sát trực tiếp 20 domain. Các site **đang chạy được**:

| Site | Tình trạng | Ghi chú |
| --- | --- | --- |
| **uukanshu.cc** (UU看書) | ✓ chạy được, adapter sẵn sàng | phồn thể |
| **czbooks.net** (小說狂人) | ✓ chạy được, adapter sẵn sàng | phồn thể |
| **qidian.com** (起点中文网) | ✓ chạy được qua `m.qidian.com` | chỉ chương miễn phí (153 của 1418 trong mẫu) |

**Các site không sử dụng được:**

| Site | Tình trạng |
| --- | --- |
| 69shuba.com, 81zw.com, twkan.com | Cloudflare chặn (trang "Just a moment...") |
| ptwxz.com (飄天文學) | có trang chống bot, encoding GB18030 |
| 3bqg.cc (笔趣阁) | redirect phức tạp, đẩy vào `/user/verify.html` |
| biquge.com, biqugee.com, xbiquge.la, uukanshu.net, b5200.net, 23us.com, trxs.cc, dxmwx.org | không kết nối được |

**Kiến trúc adapter Trung:** Mỗi kiểu site cần adapter riêng vì cấu trúc khác nhau:

- `app/sources/zh_base.py` cho uukanshu + czbooks: dùng template chung.
- `app/sources/qidian.py` cho Qidian: JSON-driven, paywall 3 lớp, số chương từ vị trí mục lục, không phải title.

### Qidian (起点中文网) — chỉ chương miễn phí

Qidian không dùng `zh_base.py` mà có adapter riêng (`app/sources/qidian.py`),
vì nó khác ba điểm, tất cả đều đã kiểm tra trực tiếp:

- **Bản desktop bị chặn.** `www.qidian.com` trả HTTP 202 với body ~209 byte
  thay vì trang thật. `m.qidian.com` trả nội dung bình thường, nên adapter làm
  việc hoàn toàn trên host mobile. Dán link `www` vẫn được: `canonical_url` tự
  đổi sang `m.`.
- **Không có gì trong HTML.** Site mobile là app vite-plugin-ssr, toàn bộ dữ
  liệu nằm trong JSON ở thẻ `<script id="vite-plugin-ssr_pageContext">`. Nên
  adapter không có selector nào, chỉ tra cứu dictionary.
- **Phần lớn truyện phải trả tiền.** Qidian cho miễn phí quyển đầu rồi thu phí
  phần còn lại.

Chương trả phí **vẫn trả HTTP 200**, kèm một đoạn teaser ngắn trong trường
`content`, nên "parse được" không đồng nghĩa với "lấy được chương". Adapter
chặn theo ba lớp:

| Lớp | Dấu hiệu | Xử lý |
| --- | --- | --- |
| Mục lục | `sS != 1` | bỏ qua, **không** tốn request |
| Nội dung chương | `vipStatus=1` và `isBuy=0` | `ChapterLocked` → `skipped_vip` |
| Nội dung chương | text ngắn hơn 30% `wordsCount` đã khai | `ChapterLocked` |

Lớp đầu là lý do adapter không nã hàng nghìn request vô ích: với truyện đã thử
(1418 chương) chỉ **153 chương miễn phí**, tức là bỏ qua được 1265 request chỉ
để nhận về teaser.

Số chương lấy theo **vị trí trong mục lục**, không lấy từ tiêu đề như các site
Trung khác, vì Qidian đánh số lại từ `第一章` ở mỗi quyển nên tiêu đề sẽ trùng
nhau giữa các quyển. Chương bị bỏ qua vẫn giữ nguyên số của nó, nhờ vậy số
chương không bị dồn lại khi mua thêm chương về sau.

Hai chi tiết nhỏ nhưng dễ mất thời gian nếu không biết:

- Trường `errorMsg` trong payload là chuỗi `"!undefined"` ở **mọi** trang, kể
  cả trang chạy tốt, nên nó không mang thông tin gì. Book id không tồn tại thể
  hiện bằng `pageData` null (kèm HTTP 404).
- Một số chương bị **đổi hình chữ** qua font riêng (`randomFont`,
  `fixedFontWoff2`). Adapter từ chối lưu những chương này, vì lưu vào sẽ được
  một mớ chữ trông như thật nhưng sai hoàn toàn — tệ hơn là báo lỗi.

Ảnh bìa được **ghép từ book id** (`bookcover.yuewen.com/qdbimg/349573/<id>/600.webp`)
chứ không scrape, vì trang mobile chỉ tham chiếu bìa qua CSS background và một
`srcset` các bản resize.

Chưa làm: mua chương bằng tài khoản. Nếu dán cookie đăng nhập vào phần Cài đặt
thì `sS` và `isBuy` sẽ phản ánh số chương đã mua, nên chương đã mua được tải về
bình thường — nhưng chỗ này chưa kiểm tra trực tiếp vì cần tài khoản có số dư.

## Dịch raw Trung sang Việt

Truyện có `lang=zh` sẽ hiện thêm nút **Dịch sang tiếng Việt** ở trang chi tiết,
hoặc gọi API:

```bash
curl -X POST "http://127.0.0.1:8000/api/novels/1/translate" \
  -H 'Content-Type: application/json' -d '{"force":false}'
```

Dịch chạy như một job nền giống crawl, nên có thanh tiến độ, tạm dừng và huỷ.
Bản dịch lưu thành file `.vi.txt` **bên cạnh** bản gốc, không ghi đè, nên dịch
lại không bao giờ làm mất nguyên văn. Chương đã dịch thì lần chạy sau bỏ qua;
muốn dịch lại hết thì dùng `force` (nút "Dịch lại toàn bộ").

Xuất bản dịch:

```bash
curl -OJ "http://127.0.0.1:8000/api/novels/1/export?format=epub&translated=true"
```

Chương nào chưa dịch sẽ tự lấy bản gốc để sách không bị đứt mạch.

### Glossary tên riêng

Máy dịch hay đọc cùng một tên nhân vật thành ba kiểu khác nhau trong một bộ
truyện dài, và đó là thứ làm bản dịch khó theo nhất. Trang chi tiết truyện có
phần **Glossary** để cố định cách đọc (ví dụ 萧炎 → Tiêu Viêm).

Tên riêng được thay **trước khi** gửi đi dịch, vì máy dịch để nguyên chữ Latin
mà nó không hiểu, còn nhờ nó dịch đúng tên thì không ăn. Sau khi dịch có thêm
một lượt sửa những tên bị máy bóp méo khoảng trắng hay viết hoa
("TiêuViêm" → "Tiêu Viêm").

Sửa glossary rồi phải bấm "Dịch lại toàn bộ", vì chương đã dịch được giữ nguyên
và bản dịch cũ còn trong cache.

### Engine dịch

| Engine | Cần key | Ghi chú |
| --- | --- | --- |
| Google Translate | không | mặc định, miễn phí, chất lượng tạm đọc |
| Gemini / OpenAI / Claude | có | văn phong tốt hơn nhiều, tính tiền theo token |

Key nhập ở trang **Cài đặt**. Google luôn nằm cuối chuỗi provider làm phương án
cuối: nếu engine trả phí hỏng key hay bị rate limit thì job vẫn chạy xong chứ
không fail.

Mỗi đoạn dịch xong được cache theo hash, nên dịch lại sau khi sửa một chương
không phải trả tiền cho cả bộ truyện. Cache tách theo từng engine, vì đổi engine
mà vẫn trả bản cũ thì sai.

### Giới hạn thật, đã kiểm tra

**Endpoint Google miễn phí rate-limit khá gắt.** Thử trên máy này: crawl 63
chương tiếng Trung rồi chạy job dịch, cả 63 chương đều trả `google: rate
limited` (HTTP 429). Thử `curl` trực tiếp tới endpoint cũng 429, nên là IP bị
chặn chứ không phải lỗi tool.

Phần pipeline vẫn hoạt động đúng: mỗi chương lỗi độc lập, job kết thúc bình
thường thay vì chết, và **không chương nào bị ghi nội dung rác** — bản gốc giữ
nguyên, `has_translation` vẫn false, lý do lỗi ghi trên từng chương.

Muốn dịch được thật thì chọn một trong hai:

- Nhập API key LLM ở trang Cài đặt (Gemini rẻ nhất trong ba cái).
- Dùng proxy ở trang Cài đặt để đổi IP ra khỏi dải đang bị Google chặn.

## Đọc truyện trên web

Bấm tên chương trong danh sách, hoặc nút **Đọc tiếp** ở thư viện và trang chi
tiết. Đường dẫn dạng `/novels/<id>/doc/<số chương>`.

- **Vị trí đọc lưu ở server**, không phải trong trình duyệt. Mở lại trên máy
  khác hay trên điện thoại sau này vẫn đúng chỗ đang đọc.
- **Cỡ chữ và bề rộng cột** lưu ở máy, vì đó là chuyện của màn hình trước mắt
  bạn chứ không phải của truyện.
- **Nền tối** dùng chung với toàn app, bấm ở góc trên bên phải.
- **Mũi tên ← →** để chuyển chương, hoặc nút ở cuối trang. Chương đầu và chương
  cuối thì nút bị khoá.
- Truyện Trung đã dịch có nút **Xem bản dịch / Xem nguyên văn**.
- Chương trước và chương sau lấy từ danh sách chương thật chứ không phải
  `số ± 1`, vì gần như site nào cũng có lỗ hổng trong cách đánh số.

API tương ứng, dùng được cho app mobile sau này:

```bash
curl "http://127.0.0.1:8000/api/novels/1/chapters/3"
curl "http://127.0.0.1:8000/api/novels/1/chapters/3?translated=true"
curl -X PUT "http://127.0.0.1:8000/api/novels/1/progress" \
  -H 'Content-Type: application/json' -d '{"chapter":3}'
```

Chương chưa tải trả về 409 kèm lý do, không phải trang trắng.

## Nâng cấp schema

Server **tự chạy migration khi khởi động**, nên nâng cấp code rồi chạy lại là
xong, không cần gõ lệnh alembic.

Lý do làm vậy: trước đây app chỉ gọi `create_all`, mà lệnh đó chỉ tạo bảng còn
thiếu chứ không bao giờ thêm cột vào bảng đã có. Khi thêm cột mới, database cũ
bị bỏ lại phía sau và mọi truy vấn chạm tới cột đó đều lỗi
(`no such column: novel.last_read_chapter`). Đây là app chạy local một người
dùng nên tự migrate là an toàn.
