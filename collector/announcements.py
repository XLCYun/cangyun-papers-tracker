"""Read the official Computer Science announcement list as one dated batch."""

from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
import math
import os
import re
import time
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen


LIST_URL = "https://arxiv.org/list/cs/new"
PAGE_SIZE = 2000
IDENTIFIER = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v[1-9]\d*)?")
CATEGORY_CODE = re.compile(r"\(([a-z-]+(?:\.[A-Za-z-]+)?)\)")


class AnnouncementError(Exception):
    """A safe diagnostic without untrusted upstream text or credentials."""


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    closed: bool = False

    def find(self, tag=None, class_name=None):
        for child in self.children:
            if isinstance(child, _Node):
                if (tag is None or child.tag == tag) and (class_name is None or class_name in child.attrs.get("class", "").split()):
                    yield child
                yield from child.find(tag, class_name)

    def text(self, *, descriptors=True):
        pieces = []
        for child in self.children:
            if isinstance(child, str):
                pieces.append(child)
            elif descriptors or "descriptor" not in child.attrs.get("class", "").split():
                pieces.append(child.text(descriptors=descriptors))
        return "".join(pieces)


class _Document(HTMLParser):
    _void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.feed(content.decode("utf-8"))
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag == "br":
            node.children.append(" ")
        if tag not in self._void:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._void:
            self.handle_endtag(tag)

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _one(nodes):
    found = list(nodes)
    if len(found) != 1:
        raise AnnouncementError("The announcement page is missing required content or contains ambiguous fields.")
    return found[0]


def _text(node, *, descriptors=True):
    return " ".join(node.text(descriptors=descriptors).split())


def _link(anchor, kind, identifier=None):
    url = urljoin("https://arxiv.org", anchor.attrs.get("href", ""))
    parsed = urlsplit(url)
    value = parsed.path.removeprefix(f"/{kind}/")
    if (parsed.scheme != "https" or parsed.netloc != "arxiv.org" or parsed.query or parsed.fragment
            or not parsed.path.startswith(f"/{kind}/") or not IDENTIFIER.fullmatch(value)
            or (identifier is not None and re.sub(r"v\d+$", "", value) != re.sub(r"v\d+$", "", identifier))):
        raise AnnouncementError("An announcement has an invalid paper link.")
    return url, value


def _entry(term, definition, kind):
    numbers = [anchor.attrs.get("name", "") for anchor in term.find("a") if re.fullmatch(r"item\d+", anchor.attrs.get("name", ""))]
    if len(numbers) != 1:
        raise AnnouncementError("An announcement has no unique sequence number.")
    abs_anchor = _one(anchor for anchor in term.find("a") if anchor.attrs.get("title") == "Abstract")
    abs_url, identifier = _link(abs_anchor, "abs")
    record = {"number": int(numbers[0][4:]), "id": identifier, "type": kind}
    if kind != "new":
        return record
    title = _text(_one(definition.find(class_name="list-title")), descriptors=False)
    abstract = _text(_one(definition.find("p", "mathjax")))
    authors = [_text(author) for author in _one(definition.find(class_name="list-authors")).find("a")]
    subjects = _one(definition.find(class_name="list-subjects"))
    categories = CATEGORY_CODE.findall(_text(subjects))
    primary = CATEGORY_CODE.findall(_text(_one(subjects.find(class_name="primary-subject"))))
    if not title or not abstract or not authors or not all(authors) or not categories or len(primary) != 1 or primary[0] not in categories:
        raise AnnouncementError("A new announcement is missing its title, abstract, authors or categories.")
    pdf = _one(anchor for anchor in term.find("a") if anchor.attrs.get("title") == "Download PDF")
    pdf_url, _ = _link(pdf, "pdf", identifier)
    html = list(anchor for anchor in term.find("a") if anchor.attrs.get("title") == "View HTML")
    if len(html) > 1:
        raise AnnouncementError("An announcement contains ambiguous HTML links.")
    html_url = _link(html[0], "html", identifier)[0] if html else None
    record["paper"] = {
        "id": identifier, "title": title, "abstract": abstract, "authors": authors,
        "affiliations": [], "categories": list(dict.fromkeys(categories)), "primaryCategory": primary[0],
        "publishedAt": None, "updatedAt": None, "announceType": "new",
        "absUrl": abs_url, "pdfUrl": pdf_url, "htmlUrl": html_url,
        "translation": {"status": "fallback", "title": title, "abstract": abstract, "brief": ""},
    }
    return record


def _parse_page(content):
    document = _Document(content).root
    if _text(_one(document.find("h1"))) != "Computer Science":
        raise AnnouncementError("The source is not the Computer Science announcement list.")
    heading = _one(node for node in document.find("h3") if _text(node).startswith("Showing new listings for "))
    try:
        day = datetime.strptime(_text(heading).removeprefix("Showing new listings for "), "%A, %d %B %Y").date()
    except ValueError:
        raise AnnouncementError("The announcement page has an invalid date.") from None
    totals = set()
    for paging in document.find(class_name="paging"):
        found = re.search(r"Total of (\d+) entries", _text(paging))
        if found:
            totals.add(int(found.group(1)))
    if len(totals) != 1 or not 0 < next(iter(totals)) <= 100000:
        raise AnnouncementError("The announcement page has no bounded, nonempty total.")
    article_lists = [node for node in document.find("dl") if node.attrs.get("id") == "articles"]
    if not article_lists or not all(articles.closed for articles in article_lists):
        raise AnnouncementError("The announcement list is truncated.")
    sections, records, term, kind, expected = {}, [], None, None, 0
    local_count = 0
    for node in (child for articles in article_lists for child in articles.children):
        if not isinstance(node, _Node):
            continue
        if node.tag == "h3":
            if kind is not None and local_count != expected:
                raise AnnouncementError("A section's displayed entry count does not match its content.")
            match = re.fullmatch(r"(New|Cross|Replacement) submissions\s*\((?:continued, )?showing (?:first |last )?(\d+) of (\d+) entries\s*\)", _text(node))
            if not match or term is not None:
                raise AnnouncementError("The announcement section header is invalid.")
            kind = {"New": "new", "Cross": "cross", "Replacement": "replace"}[match[1]]
            expected, total = int(match[2]), int(match[3])
            if kind in sections or not 0 < expected <= total:
                raise AnnouncementError("An announcement section has inconsistent counts.")
            sections[kind], local_count = total, 0
        elif node.tag == "dt":
            if term is not None or kind is None:
                raise AnnouncementError("An announcement is outside a valid section.")
            term = node
        elif node.tag == "dd":
            if term is None:
                raise AnnouncementError("An announcement is missing its identifier.")
            records.append(_entry(term, node, kind))
            local_count += 1
            term = None
    if term is not None or kind is None or local_count != expected:
        raise AnnouncementError("The announcement list is incomplete.")
    return {"date": day, "total": totals.pop(), "sections": sections, "records": records}


def _fetch(url):
    request = Request(url, headers={"User-Agent": "CangyunPapersTracker/0.1 (+https://research.cyunlab.com)", "Cache-Control": "no-cache"})
    with urlopen(request, timeout=60) as response:
        content = response.read(32 * 1024 * 1024 + 1)
    if len(content) > 32 * 1024 * 1024:
        raise AnnouncementError("The announcement page exceeds the response-size limit.")
    return content


def _batch(url, day, page_delay):
    parsed = urlsplit(url)

    def page_at(skip):
        request_url = urlunsplit(parsed._replace(query=urlencode({"skip": skip, "show": PAGE_SIZE})))
        return _parse_page(_fetch(request_url))

    first = page_at(0)
    if first["date"] != day:
        raise AnnouncementError("The announcement batch does not match the requested daily date.")
    total = first["total"]
    records, sections, identifiers = [], {}, set()
    for skip in range(0, total, PAGE_SIZE):
        if skip:
            time.sleep(page_delay)
        page = page_at(skip) if skip else first
        if page["date"] != day or page["total"] != total:
            raise AnnouncementError("The announcement batch changed during pagination.")
        if len(page["records"]) != min(PAGE_SIZE, total - skip):
            raise AnnouncementError("The announcement page is incomplete.")
        for kind, count in page["sections"].items():
            if kind in sections and sections[kind] != count:
                raise AnnouncementError("An announcement section changed during pagination.")
            sections[kind] = count
        for position, record in enumerate(page["records"], skip + 1):
            identifier = re.sub(r"v[1-9]\d*$", "", record["id"])
            if record["number"] != position or identifier in identifiers:
                raise AnnouncementError("The announcement sequence contains missing or duplicate papers.")
            identifiers.add(identifier)
            records.append(record)
    counts = {"total": total, **{kind: sections.get(kind, 0) for kind in ("new", "cross", "replace")}}
    if sum(counts[kind] for kind in ("new", "cross", "replace")) != total:
        raise AnnouncementError("The announcement section totals do not match the complete batch.")
    for position, record in enumerate(records, 1):
        expected = "new" if position <= counts["new"] else "cross" if position <= counts["new"] + counts["cross"] else "replace"
        if record["type"] != expected:
            raise AnnouncementError("An announcement is in the wrong section.")
    time.sleep(page_delay)
    if page_at(0) != first:
        raise AnnouncementError("The first announcement page changed while the batch was collected.")
    source = {"kind": "cs-announcement-list", "url": url, "announcementDate": day.isoformat(), "updatedAt": None, "counts": counts}
    return source, [record["paper"] for record in records if record["type"] == "new"]


def collect_announcements(url, day):
    """Return truthful metadata and new papers, retrying whole batches atomically."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AnnouncementError("The announcement source must be an HTTP(S) URL without query parameters or credentials.")
    attempts = int(os.environ.get("ARXIV_RETRY_ATTEMPTS", "3"))
    delay = float(os.environ.get("ARXIV_RETRY_DELAY_SECONDS", "2"))
    page_delay = float(os.environ.get("ARXIV_PAGE_DELAY_SECONDS", "3"))
    if attempts < 1 or not all(math.isfinite(value) and value >= 0 for value in (delay, page_delay)):
        raise AnnouncementError("Source retry attempts must be positive and delays must be finite and nonnegative.")
    for attempt in range(attempts):
        try:
            return _batch(url, day, page_delay)
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(delay * 2 ** attempt)
