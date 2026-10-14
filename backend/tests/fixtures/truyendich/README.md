# Fixtures: truyendich

Reproduces the **markup structure** of truyendich.vn as observed live: the
shared truyenfull template (`h1`, classless `div.info` rows labelled by `h3`,
`div.desc-text`, `#list-chapter ul.list-chapter`, `ul.pagination`,
`#chapter-c`) with this site's URL shapes — novel at `/<slug>/`, chapter list
pages at `/<slug>/trang-N/`, chapters at `/<slug>/chuong-N/`.

Differences from the truyenhoan fixtures, which are the point of having both:

- the title is a plain `<h1>` with no `title` class
- `div.info` carries extra rows (Lượt xem, Số chương, Tình trạng) around the
  ones we read, and the genre row is **plain text, not links**
- chapter link text contains stray spaces ("Chương 1  : …")

The **content is invented**: placeholder titles, author names and prose
written for these tests. No chapter text or descriptions from the site are
stored here, since that material belongs to its authors and publishers.

| file | stands for |
| --- | --- |
| `novel.html` | novel page, first page of the chapter list, pagination to page 2 |
| `novel_trang2.html` | second page of the chapter list |
| `chapter.html` | a chapter, with the ad slots and credit lines to strip |
| `homepage.html` | what the site serves for an unknown slug (no `h1`) |
