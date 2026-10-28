# Daily announcement fixtures

The fixtures contain public metadata and abstracts, not PDF files or translations.

- `announcement-papers.json` retains seven papers originally retrieved from the
  official CS RSS on 2026-10-22. Replacement cross-lists share the replacement
  section in the new HTML source. These records cover new/cross/replacement
  announcements, previously excluded CS classifications, topic and robot rules.
- `../listing_fixtures.py` renders those records and synthetic paging cases into
  the official `/list/cs/new` response structure: date/total headings, one `dl`
  per announcement section, global item numbers, metadata and abstracts. Its
  markup follows saved official pages from 2026-10-27 and 2026-10-28, including
  unversioned IDs, optional HTML links and section boundaries across pages.
- Legacy RSS-derived JSON is built explicitly in command/publisher tests to
  verify replay compatibility. The collector has no RSS runtime or test-only
  acquisition path.

The small selection is a test fixture, not an archived or complete daily batch.
Individual papers retain their original rights. Official template source:
<https://github.com/arXiv/arxiv-browse/blob/develop/browse/templates/list/list_macros.html>.
