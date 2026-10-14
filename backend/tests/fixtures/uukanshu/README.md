# Fixtures: uukanshu

Reproduces the **markup structure** of uukanshu.cc as observed live: `h1` plus
a `dl.book` info block, the whole catalogue in one `dl.book.chapterlist` with
no pagination, and the chapter body in `.content`.

Two details here are the reason this fixture exists:

- chapter URLs are `/book/<id>/<chapterId>.html` where the chapter id is a
  **database key**, so numbers have to come from the `第N章` in each title
- the newest chapter is repeated as a promo at the **top** of the list, and
  the list also contains front matter (`第0章 新書感言`) with a number of zero

The **content is invented**: placeholder titles and prose written for these
tests, in traditional Chinese to match the site. No chapter text from the site
is stored here, since that material belongs to its authors and publishers.

| file | stands for |
| --- | --- |
| `novel.html` | novel page with info block and the full chapter list |
| `chapter.html` | a chapter, with the ad slots to strip |
| `missing.html` | what the site serves for an unknown id (no `h1`) |
