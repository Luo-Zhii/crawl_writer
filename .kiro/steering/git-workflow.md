# Git workflow và quy ước commit

Áp dụng cho mọi thay đổi trong repo này.

## Commit và push thường xuyên

- Làm xong một đơn vị công việc có nghĩa (một task, một adapter, một bugfix) thì **commit ngay**, đừng dồn nhiều việc vào một commit.
- Commit xong thì **push luôn** lên remote. Không để công việc nằm ở local qua nhiều task.
- Chỉ commit khi code đã chạy được: lint sạch và test liên quan đã pass. Không commit code đang hỏng.
- Commit nhỏ, mỗi commit một chủ đề. Nếu diff đang trộn nhiều việc, tách ra thành nhiều commit.

## Branch

- **Không bao giờ push trực tiếp vào `main`.** Luôn làm việc trên feature branch.
- Đặt tên branch theo dạng `<type>/<mô-tả-ngắn>`, ví dụ `feat/novel-crawler`, `fix/epub-toc`.
- Push lần đầu dùng `git push -u origin <branch>` để set tracking.
- Khi một mảng công việc hoàn thiện thì mở PR vào `main`, không tự merge thẳng.

## Quy ước commit message (Conventional Commits)

Định dạng:

```
<type>(<scope>): <mô tả ngắn, chữ thường, không dấu chấm cuối>

<thân commit: giải thích vì sao, không chỉ cái gì>
```

`type` dùng một trong:

| type | dùng khi |
| --- | --- |
| `feat` | thêm tính năng |
| `fix` | sửa bug |
| `refactor` | đổi cấu trúc code, không đổi hành vi |
| `perf` | cải thiện hiệu năng |
| `test` | thêm hoặc sửa test |
| `docs` | tài liệu, README |
| `chore` | scaffold, cấu hình, dependency, dọn dẹp |
| `build` | thay đổi build hoặc tooling |

`scope` là phần của hệ thống bị ảnh hưởng, ví dụ: `api`, `db`, `fetch`, `sources`, `pipeline`, `translate`, `export`, `scheduler`, `frontend`, `reader`.

Ví dụ tốt:

```
feat(sources): add tangthuvien adapter with fixture test
fix(fetch): treat 200 challenge page as blocked instead of chapter body
chore(deps): pin ebooklib to 0.18
```

Quy tắc:

- Dòng tiêu đề tối đa 72 ký tự, dùng thể mệnh lệnh (`add`, không phải `added`/`adds`).
- Tiêu đề viết tiếng Anh cho nhất quán với lịch sử git. Thân commit có thể viết tiếng Việt nếu cần giải thích dài.
- Thay đổi phá vỡ tương thích thì thêm `!` sau scope và ghi rõ: `feat(api)!: rename /novels to /library`.

## Dọn dẹp định kỳ

Chạy trước mỗi lần commit:

- Xoá file tạm, file thử nghiệm, script debug đã dùng xong. Không commit rác.
- Kiểm tra `git status` để chắc không có artifact lọt vào (`dist/`, `__pycache__/`, `*.tsbuildinfo`, `.pytest_cache/`, `.ruff_cache/`, file trong `data/`). Nếu có thì bổ sung `.gitignore` chứ không add bằng `-f`.
- Không commit secret: `.env`, API key, cookie, token. Chỉ `.env.example` được commit.

Chạy định kỳ (sau mỗi vài task, hoặc khi hoàn thành một mảng lớn):

- `make clean` để xoá build artifact và cache ở local.
- Xoá branch đã merge: `git branch --merged main` rồi xoá những nhánh không còn dùng.
- `git remote prune origin` để bỏ tham chiếu tới branch đã bị xoá trên remote.
- Rà lại `data/` ở local: file export cũ và truyện không còn đọc thì xoá cho nhẹ ổ đĩa. Thư mục này không vào git nên xoá an toàn.
- Rà dependency: bỏ package không còn dùng khỏi `pyproject.toml` và `package.json`.

## An toàn

- Không dùng `git push --force`, `git reset --hard`, `git clean -fd`, `git branch -D` nếu người dùng chưa đồng ý rõ ràng.
- Không sửa `git config`.
- Không dùng `--no-verify` để bỏ qua hook.
- Ưu tiên `git add <file cụ thể>` thay vì `git add -A` để tránh commit lẫn thay đổi không liên quan.
