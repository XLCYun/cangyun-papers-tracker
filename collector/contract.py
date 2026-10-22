"""Validate the daily JSON shared by the collector, publisher and website."""

from datetime import date, datetime
from urllib.parse import urlsplit


class DailyContractError(ValueError):
    """A credential-free diagnostic for an invalid public daily document."""


def _require(condition):
    if not condition:
        raise DailyContractError("The daily JSON does not match the required data contract.")


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _timestamp(value):
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except ValueError:
        return False


def _source_url(value):
    if not _text(value):
        return False
    try:
        url = urlsplit(value)
        return url.scheme in {"http", "https"} and bool(url.hostname) and not (url.username or url.password)
    except ValueError:
        return False


def _paper_url(value, path):
    if not _text(value):
        return False
    try:
        url = urlsplit(value)
        return url.scheme == "https" and url.netloc == "arxiv.org" and url.path.startswith(f"/{path}/") and bool(url.path[len(path) + 2:])
    except ValueError:
        return False


def validate_daily(daily, requested):
    """Reject incomplete source metadata, translations and inconsistent counts."""
    _require(isinstance(daily, dict) and type(daily.get("schemaVersion")) is int and daily["schemaVersion"] == 1)
    _require(isinstance(daily.get("date"), str) and daily["date"] == requested)
    try:
        _require(date.fromisoformat(daily["date"]).isoformat() == daily["date"])
    except ValueError:
        raise DailyContractError("The daily JSON date is invalid.") from None
    _require(daily.get("timezone") == "Asia/Shanghai" and _timestamp(daily.get("fetchedAt")))
    source = daily.get("source")
    _require(isinstance(source, dict) and _source_url(source.get("url")) and _timestamp(source.get("updatedAt")))
    _require("generatedAt" not in source or _timestamp(source["generatedAt"]))
    papers, stats = daily.get("papers"), daily.get("stats")
    _require(isinstance(papers, list) and isinstance(stats, dict))
    _require(all(type(stats.get(name)) is int and stats[name] >= 0 for name in ("fetched", "matched", "translated", "fallback")))
    _require(stats["matched"] == len(papers) and stats["fetched"] >= len(papers))
    identifiers, states = set(), []
    for paper in papers:
        _require(isinstance(paper, dict) and _text(paper.get("id")) and paper["id"] not in identifiers)
        identifiers.add(paper["id"])
        _require(all(_text(paper.get(field)) for field in ("title", "abstract")))
        _require(all(isinstance(paper.get(field), list) and all(_text(value) for value in paper[field])
                     for field in ("authors", "affiliations", "categories")))
        _require(isinstance(paper.get("primaryCategory"), str) and _timestamp(paper.get("publishedAt")))
        _require("updatedAt" in paper and (paper["updatedAt"] is None or _timestamp(paper["updatedAt"])))
        _require(paper.get("announceType") in {"new", "cross", "replace", "replace-cross"})
        _require(all(_paper_url(paper.get(field), path) for field, path in (("absUrl", "abs"), ("pdfUrl", "pdf"), ("htmlUrl", "html"))))
        translation = paper.get("translation")
        _require(isinstance(translation, dict) and translation.get("status") in {"translated", "fallback"})
        _require(all(_text(translation.get(field)) for field in ("title", "abstract")) and isinstance(translation.get("brief"), str))
        if translation["status"] == "fallback":
            _require(translation["title"] == paper["title"] and translation["abstract"] == paper["abstract"] and translation["brief"] == "")
        else:
            _require(_text(translation["brief"]))
        states.append(translation["status"])
    _require(stats["translated"] == states.count("translated") and stats["fallback"] == states.count("fallback"))
