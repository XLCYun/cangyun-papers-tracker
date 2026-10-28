"""Validate the daily JSON shared by the collector, publisher and website."""

from datetime import date, datetime
import math
import re
from urllib.parse import urlsplit

from .tagging import TAGS, derive_tags, valid_scores


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


def _validate_source(source, requested, stats, papers):
    _require(isinstance(source, dict) and _source_url(source.get("url")))
    if "kind" not in source:
        _require(_timestamp(source.get("updatedAt")))
        _require("generatedAt" not in source or _timestamp(source["generatedAt"]))
        return
    _require(source.get("kind") in {"cs-announcement-list", "announcement-schedule"})
    _require("updatedAt" in source and source["updatedAt"] is None)
    _require(type(stats.get("duplicates")) is int and stats["duplicates"] >= 0)
    if source["kind"] == "announcement-schedule":
        _require(source.get("reason") == "weekend" and date.fromisoformat(requested).weekday() >= 5)
        _require(not papers and all(stats[name] == 0 for name in ("fetched", "matched", "translated", "fallback", "duplicates")))
        return
    _require(source.get("announcementDate") == requested)
    counts = source.get("counts")
    _require(isinstance(counts, dict) and set(counts) == {"total", "new", "cross", "replace"})
    _require(all(type(value) is int and value >= 0 for value in counts.values()))
    _require(counts["total"] > 0 and counts["total"] == counts["new"] + counts["cross"] + counts["replace"])
    _require(stats["fetched"] == counts["total"] and stats["matched"] + stats["duplicates"] <= counts["new"])


def _validate_tagging(paper, *, allow_stale_tags):
    if "tags" not in paper and "tagging" not in paper:
        return
    tags, tagging = paper.get("tags"), paper.get("tagging")
    _require(isinstance(tags, list) and all(isinstance(label, str) and label in TAGS for label in tags))
    _require(tags == [label for label in TAGS if label in tags])
    _require(isinstance(tagging, dict) and set(tagging) == {
        "status", "model", "rulesVersion", "threshold", "inputSha256", "scores",
    })
    _require(tagging["status"] in {"tagged", "fallback"})
    _require(_text(tagging["model"]) and _text(tagging["rulesVersion"]))
    threshold = tagging["threshold"]
    _require(type(threshold) in (int, float) and math.isfinite(threshold) and 0 <= threshold <= 1)
    _require(isinstance(tagging["inputSha256"], str) and re.fullmatch(r"[a-f0-9]{64}", tagging["inputSha256"]))
    _require(valid_scores(tagging["scores"], allow_legacy=tagging["rulesVersion"] == "daily-tags-v1")
             if tagging["status"] == "tagged" else tagging["scores"] == {})
    if not allow_stale_tags:
        _require(tags == derive_tags(paper, tagging["scores"], threshold))


def validate_daily(daily, requested, *, allow_stale_tags=False):
    """Reject incomplete source metadata, translations and inconsistent counts."""
    _require(isinstance(daily, dict) and type(daily.get("schemaVersion")) is int and daily["schemaVersion"] == 1)
    _require(isinstance(daily.get("date"), str) and daily["date"] == requested)
    try:
        _require(date.fromisoformat(daily["date"]).isoformat() == daily["date"])
    except ValueError:
        raise DailyContractError("The daily JSON date is invalid.") from None
    _require(daily.get("timezone") == "Asia/Shanghai" and _timestamp(daily.get("fetchedAt")))
    source = daily.get("source")
    papers, stats = daily.get("papers"), daily.get("stats")
    _require(isinstance(papers, list) and isinstance(stats, dict))
    _require(all(type(stats.get(name)) is int and stats[name] >= 0 for name in ("fetched", "matched", "translated", "fallback")))
    _require(stats["matched"] == len(papers) and stats["fetched"] >= len(papers))
    _validate_source(source, requested, stats, papers)
    listing = source.get("kind") == "cs-announcement-list"
    identifiers, states = set(), []
    for paper in papers:
        _require(isinstance(paper, dict) and _text(paper.get("id")) and paper["id"] not in identifiers)
        identifiers.add(paper["id"])
        _require(all(_text(paper.get(field)) for field in ("title", "abstract")))
        _require(all(isinstance(paper.get(field), list) and all(_text(value) for value in paper[field])
                     for field in ("authors", "affiliations", "categories")))
        _require(isinstance(paper.get("primaryCategory"), str) and "publishedAt" in paper)
        _require(paper["publishedAt"] is None if listing else _timestamp(paper["publishedAt"]))
        _require("updatedAt" in paper and (paper["updatedAt"] is None or _timestamp(paper["updatedAt"])))
        _require(paper.get("announceType") in {"new", "cross", "replace", "replace-cross"})
        if listing:
            _require(paper["updatedAt"] is None and paper["announceType"] == "new")
        _require(all(_paper_url(paper.get(field), path) for field, path in (("absUrl", "abs"), ("pdfUrl", "pdf"))))
        _require("htmlUrl" in paper and ((listing and paper["htmlUrl"] is None) or _paper_url(paper["htmlUrl"], "html")))
        if listing:
            base_id = re.sub(r"v[1-9]\d*$", "", paper["id"])
            for field, kind in (("absUrl", "abs"), ("pdfUrl", "pdf"), ("htmlUrl", "html")):
                if paper[field] is not None:
                    link = urlsplit(paper[field])
                    _require(not link.query and not link.fragment)
                    _require(re.sub(r"v[1-9]\d*$", "", link.path.removeprefix(f"/{kind}/")) == base_id)
        translation = paper.get("translation")
        _require(isinstance(translation, dict) and translation.get("status") in {"translated", "fallback"})
        _require(all(_text(translation.get(field)) for field in ("title", "abstract")) and isinstance(translation.get("brief"), str))
        if translation["status"] == "fallback":
            _require(translation["title"] == paper["title"] and translation["abstract"] == paper["abstract"] and translation["brief"] == "")
        else:
            _require(_text(translation["brief"]))
        _validate_tagging(paper, allow_stale_tags=allow_stale_tags)
        states.append(translation["status"])
    _require(stats["translated"] == states.count("translated") and stats["fallback"] == states.count("fallback"))
