"""Exercise complete announcement pagination through the collector command."""

import json
import hashlib

import pytest

from listing_fixtures import LIST_PATH, listing_page, listing_response, selected_entries
from test_collector import NOW, service


@pytest.fixture(autouse=True)
def no_external_models_or_delays(monkeypatch):
    for name in ("OPENAI_API_KEY", "JEV_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARXIV_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("ARXIV_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("ARXIV_PAGE_DELAY_SECONDS", "0")


def test_command_reads_listing_and_preserves_unknown_timestamps(tmp_path, monkeypatch):
    from collector import main

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("ARXIV_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("ARXIV_PAGE_DELAY_SECONDS", "0")
    with service({LIST_PATH: (200, listing_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        # Prevent accidentally using the old production RSS implementation.
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/unsupported-rss")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["source"] == {
        "kind": "cs-announcement-list", "url": origin + "/list/cs/new",
        "announcementDate": "2026-10-22", "updatedAt": None,
        "counts": {"total": 1, "new": 1, "cross": 0, "replace": 0},
    }
    assert daily["papers"][0]["publishedAt"] is None
    assert daily["papers"][0]["updatedAt"] is None
    assert daily["papers"][0]["primaryCategory"] == "cs.LG"
    assert daily["stats"]["duplicates"] == 0


def test_command_pages_all_sections_when_new_papers_span_the_page_limit(tmp_path, monkeypatch):
    from collector import main

    template = selected_entries("2610.28637v1")[0]
    papers = [{**template, "id": f"2610.{position:05}", "title": "Nonmatching research"} for position in range(1, 2004)]
    for paper in papers:
        paper["abstract"] = "A study without topic keywords."
    papers[2000].update(title="Browser Agent research", categories=["cs.CV"])
    papers[2001]["type"] = "cross"
    papers[2002]["type"] = "replace"
    requests = []

    def response(skip):
        def get():
            requests.append(skip)
            return 200, listing_page(papers, skip=skip)
        return get

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.setenv("ARXIV_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("ARXIV_PAGE_DELAY_SECONDS", "0")
    with service({LIST_PATH: response(0), "/list/cs/new?skip=2000&show=2000": response(2000)}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["stats"] == {"fetched": 2003, "matched": 1, "translated": 0, "fallback": 1, "duplicates": 0}
    assert daily["source"]["counts"] == {"total": 2003, "new": 2001, "cross": 1, "replace": 1}
    assert [paper["id"] for paper in daily["papers"]] == ["2610.02001"]
    assert requests == [0, 2000, 0]


@pytest.mark.parametrize("defect", ["old-first-page", "old-second-page", "missing-last-entry", "duplicate-id",
                                        "skipped-number", "changed-total", "changed-section", "changed-first-page"])
def test_command_rejects_incomplete_or_changing_pagination_before_models(tmp_path, monkeypatch, defect):
    from collector import main

    template = selected_entries("2610.28637v1")[0]
    papers = [{**template, "id": f"2610.{position:05}"} for position in range(1, 2002)]
    first = listing_page(papers)
    last = listing_page(papers, skip=2000)
    repeated = first
    if defect == "old-first-page":
        first = first.replace(b"22 October", b"21 October")
    elif defect == "old-second-page":
        last = last.replace(b"22 October", b"21 October")
    elif defect == "missing-last-entry":
        last = last[:last.index(b"<dt>")] + b"</dl></body></html>"
    elif defect == "duplicate-id":
        last = last.replace(b"2610.02001", b"2610.00001")
    elif defect == "skipped-number":
        last = last.replace(b"name='item2001'", b"name='item2002'")
    elif defect == "changed-total":
        last = last.replace(b"Total of 2001", b"Total of 2002")
    elif defect == "changed-section":
        last = last.replace(b"of 2001 entries", b"of 2002 entries")
    else:
        repeated = repeated.replace(b"To Keep or Not to Keep:", b"A revised title:")
    first_responses = iter([first, repeated])
    called_models = []

    def model(request):
        called_models.append(request)
        return 503, b"must not call models for an invalid batch"

    previous_index = b'{"schemaVersion":1,"updatedAt":null,"days":[]}\n'
    (tmp_path / "index.json").write_bytes(previous_index)
    with service({LIST_PATH: lambda: (200, next(first_responses)),
                  "/list/cs/new?skip=2000&show=2000": (200, last),
                  "/v1/chat/completions": model, "/typesafe/v1/systemone": model}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "fixture-only")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1

    assert not called_models
    assert not (tmp_path / "2026-10-22.json").exists()
    assert (tmp_path / "index.json").read_bytes() == previous_index


def test_command_restarts_the_entire_batch_when_the_first_page_changes(tmp_path, monkeypatch):
    from collector import main

    paper = selected_entries("2610.28637v1")[0]
    original = listing_page([paper])
    revised = listing_page([{**paper, "title": "LLM revised study"}])
    responses = iter([original, revised, revised, revised])
    calls = []

    def source():
        calls.append(True)
        return 200, next(responses)

    monkeypatch.setenv("ARXIV_RETRY_ATTEMPTS", "2")
    with service({LIST_PATH: source}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert len(calls) == 4
    assert daily["papers"][0]["title"] == "LLM revised study"


def test_command_does_not_invent_html_links_or_timestamps_and_ignores_unused_metadata(tmp_path, monkeypatch):
    from collector import main

    paper = selected_entries("2610.28637v1")[0]
    paper.update(id="2610.28637", htmlUrl=None, title="LLM & Agent research", categories=["cs.CV", "math.NA"])
    replacement = {**paper, "id": "2501.00002v3", "type": "replace", "abstract": "", "authors": []}
    content = listing_page([paper, replacement])
    with service({LIST_PATH: (200, content)}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    item = daily["papers"][0]
    assert item["id"] == "2610.28637"
    assert item["title"] == "LLM & Agent research"
    assert item["categories"] == ["cs.CV", "math.NA"]
    assert item["htmlUrl"] is None and item["publishedAt"] is None and item["updatedAt"] is None
    assert daily["source"]["counts"] == {"total": 2, "new": 1, "cross": 0, "replace": 1}


def test_publisher_checks_new_listing_provenance_and_unknown_timestamps(tmp_path, monkeypatch):
    from collector import main
    from collector.publish import main as publish

    paper = selected_entries("2610.28637v1")[0]
    paper["htmlUrl"] = None
    with service({LIST_PATH: (200, listing_page([paper]))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    assert publish(["--date", "2026-10-22", "--data-dir", str(tmp_path), "--check"]) == 0


def test_publisher_rejects_new_listing_links_for_a_different_paper(tmp_path, monkeypatch):
    from collector import main
    from collector.publish import main as publish

    with service({LIST_PATH: (200, listing_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    assert publish(["--date", "2026-10-22", "--data-dir", str(tmp_path), "--check"]) == 0
    path = tmp_path / "2026-10-22.json"
    daily = json.loads(path.read_text())
    daily["papers"][0]["pdfUrl"] = "https://arxiv.org/pdf/2610.99999"
    content = json.dumps(daily).encode()
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    index_path = tmp_path / "index.json"
    index = json.loads(index_path.read_text())
    index["days"][0].update(sha256=digest, file=f"2026-10-22/{digest}.json")
    index_path.write_text(json.dumps(index))
    assert publish(["--date", "2026-10-22", "--data-dir", str(tmp_path), "--check"]) == 1
