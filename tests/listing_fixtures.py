"""Public HTML responses matching arXiv's announcement-list markup."""

from copy import deepcopy
from datetime import date
from html import escape
import json
from pathlib import Path


PAPERS = json.loads((Path(__file__).parent / "fixtures/announcement-papers.json").read_text())
DAY = "2026-10-22"
LIST_PATH = "/list/cs/new?skip=0&show=2000"


def selected_entries(*ids):
    return deepcopy([paper for paper in PAPERS if not ids or paper["id"] in ids])


def listing_page(papers, *, day=DAY, skip=0, show=2000):
    ordered = [paper for kind in ("new", "cross", "replace") for paper in papers if paper["type"] == kind]
    visible = ordered[skip:skip + show]
    content = ["<!doctype html><html><body><h1>Computer Science</h1>",
               f"<h3>Showing new listings for {date.fromisoformat(day).strftime('%A, %-d %B %Y')}</h3>",
               f"<div class='paging'>Total of {len(ordered)} entries : "
               f"<span>{skip + 1}-{skip + len(visible)}</span></div>"]
    names = {"new": "New", "cross": "Cross", "replace": "Replacement"}
    for kind in names:
        section = [paper for paper in visible if paper["type"] == kind]
        if not section:
            continue
        total = sum(paper["type"] == kind for paper in papers)
        content.append(f"<dl id='articles'><h3>{names[kind]} submissions (showing {len(section)} of {total} entries)</h3>")
        for paper in section:
            position = skip + visible.index(paper) + 1
            identifier = escape(paper["id"])
            html_url = paper.get("htmlUrl", f"https://arxiv.org/html/{paper['id']}")
            html_link = f'<a href="{escape(html_url)}" title="View HTML">html</a>' if html_url else ""
            authors = ", ".join(f'<a href="/search/cs?searchtype=author">{escape(author)}</a>' for author in paper["authors"])
            categories = "; ".join(f"Field ({escape(category)})" for category in paper["categories"][1:])
            primary = f'Field ({escape(paper["categories"][0])})' if paper["categories"] else ""
            content.append(f'''<dt><a name='item{position}'>[{position}]</a>
<a href ="/abs/{identifier}" title="Abstract" id="{identifier}">arXiv:{identifier}</a>
[<a href="/pdf/{identifier}" title="Download PDF">pdf</a>{html_link}]</dt>
<dd><div class='meta'>
<div class='list-title mathjax'><span class='descriptor'>Title:</span>{escape(paper['title'])}</div>
<div class='list-authors'>{authors}</div>
<div class='list-subjects'><span class='descriptor'>Subjects:</span><span class="primary-subject">{primary}</span>; {categories}</div>
<p class='mathjax'>{escape(paper['abstract'])}</p>
</div></dd>''')
        content.append("</dl>")
    return ("\n".join(content) + "</body></html>").encode()


def listing_response(*ids):
    return listing_page(selected_entries(*ids))


def tagging_listing(*papers):
    entries = []
    for position, fields in enumerate(papers, 1):
        entry = selected_entries("2610.28637v1")[0]
        entry.update({"id": f"2610.{position:05d}v1", "categories": ["cs.AI"], **fields})
        entries.append(entry)
    return listing_page(entries)
