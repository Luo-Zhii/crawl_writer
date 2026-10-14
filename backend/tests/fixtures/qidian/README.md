# Fixtures: qidian

Reproduces the **payload structure** of `m.qidian.com` as observed live. Qidian
puts nothing useful in its markup: the mobile site is a vite-plugin-ssr app that
ships every page as JSON inside a `vite-plugin-ssr_pageContext` script tag, so
these fixtures are that script tag plus a minimal HTML shell.

Only the fields the adapter actually reads are kept. The live payload has
roughly 35 top-level keys on the book page alone (ads, fan rankings, month
ticket counts, recommendation carousels); carrying them would make the fixtures
unreadable without testing anything.

Three details here are the reason this fixture exists:

- the **desktop** host answers a plain request with HTTP 202 and a ~200 byte
  body and no payload at all, which `blocked.html` stands in for
- most of the book is paid: the catalogue flags readability per chapter with
  `sS`, and a fetched chapter reports `vipStatus` plus `isBuy`
- a paywalled chapter still returns 200 with a short **teaser** in `content`,
  so "it parsed" is not the same as "we got the chapter"

The **content is invented**: placeholder titles and prose written for these
tests, in simplified Chinese to match the site. No text from Qidian is stored
here, since that material belongs to its authors and publishers.

| file | stands for |
| --- | --- |
| `novel.html` | book page: title, author, description, genres, status |
| `catalog.html` | catalogue: one free volume, one paid volume with a free extra |
| `chapter_free.html` | a free chapter, full text |
| `chapter_paid.html` | a paid chapter: teaser only, `vipStatus=1 isBuy=0` |
| `chapter_bought.html` | a paid chapter this session owns, `isBuy=1` |
| `chapter_font.html` | a chapter scrambled through a per-chapter font |
| `blocked.html` | what the gated desktop host returns: no payload |
| `notfound.html` | unknown book id: payload present, `pageData` null |

One field is deliberately *not* trusted: `errorMsg` is the literal string
`"!undefined"` on every page observed live, working pages included, so it
carries no signal. An unknown book id shows up as a null `pageData` instead.
