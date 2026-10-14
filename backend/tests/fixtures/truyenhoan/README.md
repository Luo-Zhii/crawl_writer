# Fixtures: truyenhoan

These files reproduce the **markup structure** of truyenhoan.com as observed
live (tag names, classes, ids, URL shapes, the order of the info rows), so the
adapter's selectors are tested against the real layout.

The **content is invented**: placeholder novel titles, author names and prose
written for these tests. No chapter text or descriptions from the site are
stored here, since that material belongs to its authors and publishers.

Files:

| file | stands for |
| --- | --- |
| `novel.html` | novel page, first page of the chapter list, pagination to page 3 |
| `novel_trang2.html` | second page of the chapter list |
| `novel_trang3.html` | last page, with a gap in the chapter numbering |
| `chapter.html` | a chapter, including the ad slots and credit lines to strip |
| `chapter_empty.html` | chapter page whose body container is missing |
| `homepage.html` | what the site serves for an unknown novel id (no `h1.title`) |
| `search.html` | search results page |

When the site changes its layout, re-check the selectors live and update both
the adapter and these files together.
