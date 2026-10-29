"""Exercise the supported collector command against external HTTP fixtures."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Lock, Thread
from urllib.parse import urlsplit

from listing_fixtures import listing_response, listing_page, selected_entries, tagging_listing

import pytest


NOW = datetime.fromisoformat("2026-10-22T13:30:00+08:00")


@pytest.fixture(autouse=True)
def fixture_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_THINKING", raising=False)
    monkeypatch.setenv("ARXIV_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("ARXIV_PAGE_DELAY_SECONDS", "0")
    for name in ("JEV_API_KEY", "JEV_BASE_URL", "JEV_MODEL", "JEV_THRESHOLD", "JEV_RULES_VERSION", "JEV_WORKERS", "JEV_RETRY_ATTEMPTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JEV_RETRY_DELAY_SECONDS", "0")


def model_response(translations):
    return json.dumps({"choices": [{"message": {"content": json.dumps({"translations": translations}, ensure_ascii=False)}}]}).encode()


def jev_response(scores):
    scores = {"gui_agent": 0, **scores}
    return json.dumps({"model": "jev-1.13.0", "answers": {
        name: {"type": "noul", "noul": value} for name, value in scores.items()
    }}).encode()


@contextmanager
def service(routes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = routes.get(self.path, routes.get(urlsplit(self.path).path, (404, b"unexpected fixture request")))
            status, body = route() if callable(route) else route
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            route = routes.get(self.path, routes.get(urlsplit(self.path).path, (404, b"unexpected fixture request")))
            status, body = route(request) if callable(route) else route
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_command_archives_official_metadata_and_english_fallback(tmp_path, monkeypatch):
    from collector import main

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with service({"/list/cs/new": (200, listing_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert (daily["schemaVersion"], daily["date"], daily["timezone"], daily["fetchedAt"]) == (
        1, "2026-10-22", "Asia/Shanghai", "2026-10-22T13:30:00+08:00"
    )
    assert daily["source"]["updatedAt"] is None
    assert daily["source"]["announcementDate"] == "2026-10-22"
    assert daily["stats"] == {"fetched": 1, "matched": 1, "translated": 0, "fallback": 1, "duplicates": 0}
    paper = daily["papers"][0]
    assert (paper["id"], paper["authors"], paper["categories"], paper["announceType"]) == (
        "2610.28637v1", ["Dong Liu", "Yanxuan Yu", "Eric Jiang", "Shu Wang", "Ying Nian Wu"],
        ["cs.LG", "cs.DC"], "new"
    )
    assert paper["primaryCategory"] == "cs.LG"
    assert paper["affiliations"] == []
    assert paper["updatedAt"] is None
    assert paper["publishedAt"] is None
    assert paper["pdfUrl"] == "https://arxiv.org/pdf/2610.28637v1"
    assert paper["htmlUrl"] == "https://arxiv.org/html/2610.28637v1"
    assert paper["title"].startswith("To Keep or Not to Keep:")
    assert paper["abstract"].startswith("Disaggregated")
    assert paper["translation"] == {
        "status": "fallback", "title": paper["title"], "abstract": paper["abstract"], "brief": ""
    }
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["days"][0]["date"] == "2026-10-22"
    assert index["days"][0]["count"] == 1
    assert len(index["days"][0]["sha256"]) == 64


def test_command_keeps_only_new_and_topics_across_all_cs_categories_before_translation(tmp_path, monkeypatch):
    from collector import main

    submitted = []

    def model(request):
        papers = json.loads(request["messages"][1]["content"].split("论文资料：\n", 1)[1])
        submitted.extend(paper["id"] for paper in papers)
        return 503, b"fixture translation unavailable"

    with service({"/list/cs/new": (200, listing_response()), "/v1/chat/completions": model}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert [(paper["id"], paper["announceType"]) for paper in daily["papers"]] == [
        ("2610.28637v1", "new"), ("2610.29003v1", "new"),
    ]
    assert submitted == ["2610.28637v1", "2610.29003v1"]
    assert daily["stats"] == {"fetched": 7, "matched": 2, "translated": 0, "fallback": 2, "duplicates": 0}


def test_command_archives_zero_when_only_other_announcement_types_match(tmp_path, monkeypatch):
    from collector import main

    with service({"/list/cs/new": (200, listing_response("2609.00755v1", "2106.06060v5", "2608.15900v2"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["papers"] == []
    assert daily["stats"] == {"fetched": 3, "matched": 0, "translated": 0, "fallback": 0, "duplicates": 0}
    assert json.loads((tmp_path / "index.json").read_text())["days"][0]["count"] == 0


def test_command_refilters_legacy_archive_without_retranslating_or_fetching_source(tmp_path, monkeypatch):
    from collector import main

    with service({"/list/cs/new": (200, listing_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    path = tmp_path / "2026-10-22.json"
    legacy = json.loads(path.read_text())
    legacy["source"] = {"url": "https://rss.arxiv.org/rss/cs", "updatedAt": "2026-10-22T00:00:00-04:00"}
    legacy["papers"][0]["publishedAt"] = "2026-10-22T00:00:00-04:00"
    kept = legacy["papers"][0]
    kept["translation"] = {"status": "translated", "title": "已成功标题", "abstract": "已成功摘要。", "brief": "已成功总结。"}
    expected = deepcopy(kept)
    for identifier, kind in [("2610.00002v1", "cross"), ("2610.00003v2", "replace"), ("2610.00004v2", "replace-cross")]:
        removed = deepcopy(kept)
        removed.update(id=identifier, announceType=kind,
                       absUrl=f"https://arxiv.org/abs/{identifier}", pdfUrl=f"https://arxiv.org/pdf/{identifier}", htmlUrl=f"https://arxiv.org/html/{identifier}")
        removed["translation"] = {"status": "fallback", "title": removed["title"], "abstract": removed["abstract"], "brief": ""}
        legacy["papers"].append(removed)
    legacy["stats"] = {"fetched": 4, "matched": 4, "translated": 1, "fallback": 3}
    content = (json.dumps(legacy, ensure_ascii=False, indent=2) + "\n").encode()
    path.write_bytes(content)
    index_path = tmp_path / "index.json"
    index = json.loads(index_path.read_text())
    digest = hashlib.sha256(content).hexdigest()
    index["days"][0].update(count=4, sha256=digest, file=f"2026-10-22/{digest}.json")
    index_path.write_text(json.dumps(index) + "\n")

    requests = []

    def unexpected_translation(request):
        requests.append(request)
        return 503, b"translation should not be called"

    with service({"/list/cs/new": (503, b"source should not be fetched"), "/v1/chat/completions": unexpected_translation}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads(path.read_text())
    assert daily["papers"] == [expected]
    assert daily["source"] == legacy["source"]
    assert daily["fetchedAt"] == legacy["fetchedAt"]
    assert daily["stats"] == {"fetched": 4, "matched": 1, "translated": 1, "fallback": 0}
    assert requests == []
    entry = json.loads(index_path.read_text())["days"][0]
    assert entry["count"] == 1 and entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_command_publishes_compatible_model_translation_without_losing_originals(tmp_path, monkeypatch):
    from collector import main

    model_response = {"choices": [{"message": {"content": json.dumps({"translations": [{
        "id": "2610.28637v1", "chinese_title": "缓存保留研究", "chinese_summary": "示例译文。", "brief_summary": "针对缓存问题，通过学习方法选择保留内容。"
    }]}, ensure_ascii=False)}}]}
    with service({
        "/list/cs/new": (200, listing_response("2610.28637v1")),
        "/v1/chat/completions": (200, json.dumps(model_response).encode()),
    }) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("OPENAI_MODEL", "fixture-model")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["papers"][0]["translation"] == {
        "status": "translated", "title": "缓存保留研究", "abstract": "示例译文。", "brief": "针对缓存问题，通过学习方法选择保留内容。"
    }
    assert daily["papers"][0]["abstract"].startswith("Disaggregated")
    assert daily["stats"] == {"fetched": 1, "matched": 1, "translated": 1, "fallback": 0, "duplicates": 0}


def test_command_replays_archived_day_without_fetching_current_feed_or_retranslating_success(tmp_path, monkeypatch):
    from collector import main

    first_translation = {"id": "2610.28637v1", "chinese_title": "已成功标题", "chinese_summary": "已成功摘要。", "brief_summary": "已成功总结。"}
    retry_translation = {"id": "2610.29003v1", "chinese_title": "补译标题", "chinese_summary": "补译摘要。", "brief_summary": "补译总结。"}
    feed = listing_response("2610.28637v1", "2610.29003v1")
    with service({"/list/cs/new": (200, feed), "/v1/chat/completions": (200, model_response([first_translation]))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    def retry_model(request):
        submitted = json.loads(request["messages"][1]["content"].split("论文资料：\n", 1)[1])
        if [paper["id"] for paper in submitted] != ["2610.29003v1"]:
            return 400, b"unexpected repeat translation"
        return 200, model_response([retry_translation])

    with service({"/list/cs/new": (503, b"unavailable"), "/v1/chat/completions": retry_model}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)], now=datetime.fromisoformat("2026-10-23T13:30:00+08:00")) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["source"]["url"] != origin + "/list/cs/new"
    assert daily["fetchedAt"] == "2026-10-22T13:30:00+08:00"
    assert daily["source"]["updatedAt"] is None
    assert daily["source"]["announcementDate"] == "2026-10-22"
    assert json.loads((tmp_path / "index.json").read_text())["updatedAt"] == "2026-10-23T13:30:00+08:00"
    assert [(paper["translation"]["status"], paper["translation"]["title"]) for paper in daily["papers"]] == [("translated", "已成功标题"), ("translated", "补译标题")]
    assert daily["stats"] == {"fetched": 2, "matched": 2, "translated": 2, "fallback": 0, "duplicates": 0}


def test_command_refuses_to_label_the_current_feed_as_missing_history(tmp_path, monkeypatch):
    from collector import main

    with service({"/list/cs/new": (200, listing_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--date", "2026-10-21", "--output-dir", str(tmp_path)], now=NOW) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("batch_date", ["2026-10-22", "2026-10-21"])
def test_command_refuses_empty_or_stale_weekday_sources(tmp_path, monkeypatch, batch_date):
    from collector import main

    with service({"/list/cs/new": (200, listing_page([], day=batch_date))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("response", [
    b"<html><body><dl id='articles'>",
    b"<html><body>rate limit</body></html>",
    b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>error</id></entry></feed>',
    listing_response("2610.28637v1").replace(b"To Keep or Not to Keep: Learning KV Cache Retention in Disaggregated LLM Serving Systems", b""),
    listing_response("2610.28637v1").replace(b"(cs.LG)", b"").replace(b"(cs.DC)", b""),
], ids=["truncated-html", "html-challenge", "atom-error", "missing-title", "missing-categories"])
def test_command_rejects_invalid_source_without_changing_the_last_valid_index(tmp_path, monkeypatch, response):
    from collector import main

    previous = b'{"schemaVersion":1,"updatedAt":null,"days":[]}\n'
    (tmp_path / "index.json").write_bytes(previous)
    with service({"/list/cs/new": (200, response)}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert (tmp_path / "index.json").read_bytes() == previous
    assert not (tmp_path / "2026-10-22.json").exists()


def test_command_retries_a_transient_source_limit_then_archives_the_complete_batch(tmp_path, monkeypatch):
    from collector import main

    responses = iter([(429, b"temporarily limited"), (200, listing_response("2610.28637v1")), (200, listing_response("2610.28637v1"))])
    with service({"/list/cs/new": lambda: next(responses)}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("ARXIV_RETRY_DELAY_SECONDS", "0")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    assert json.loads((tmp_path / "2026-10-22.json").read_text())["stats"]["matched"] == 1


@pytest.mark.parametrize("status,response", [
    (402, b'private provider body: fixture-not-a-secret'),
    (429, b'private provider body: fixture-not-a-secret'),
    (200, b'{"choices":[]}'),
    (200, model_response([{"id": "2610.28637v1", "chinese_title": "missing fields"}])),
], ids=["balance", "rate-limit", "invalid-response", "incomplete-translation"])
def test_translation_failures_keep_complete_english_without_publishing_provider_details(tmp_path, monkeypatch, capsys, status, response):
    from collector import main

    with service({"/list/cs/new": (200, listing_response("2610.28637v1")), "/v1/chat/completions": (status, response)}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    content = (tmp_path / "2026-10-22.json").read_text()
    paper = json.loads(content)["papers"][0]
    assert paper["translation"] == {"status": "fallback", "title": paper["title"], "abstract": paper["abstract"], "brief": ""}
    output = capsys.readouterr()
    assert "fixture-not-a-secret" not in content + output.out + output.err
    assert "private provider body" not in content + output.out + output.err


def test_permanent_source_failure_keeps_existing_index_and_logs_only_safe_status(tmp_path, monkeypatch, capsys):
    from collector import main

    previous = b'{"schemaVersion":1,"updatedAt":null,"days":[]}\n'
    (tmp_path / "index.json").write_bytes(previous)
    with service({"/list/cs/new": (503, b'private upstream response')}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert (tmp_path / "index.json").read_bytes() == previous
    assert not (tmp_path / "2026-10-22.json").exists()
    error = capsys.readouterr().err
    assert "HTTP 503" in error
    assert "private upstream response" not in error


@pytest.mark.parametrize("defect", ["wrong-date", "wrong-schema", "unknown-translation-state", "missing-translation-title"])
def test_command_does_not_overwrite_an_invalid_archived_source(tmp_path, monkeypatch, defect):
    from collector import main

    with service({"/list/cs/new": (200, listing_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    path = tmp_path / "2026-10-22.json"
    daily = json.loads(path.read_text())
    if defect == "wrong-date":
        daily["date"] = "2026-10-21"
    elif defect == "wrong-schema":
        daily["schemaVersion"] = 99
    elif defect == "unknown-translation-state":
        daily["papers"][0]["translation"]["status"] = "unknown"
    else:
        del daily["papers"][0]["translation"]["title"]
    original = json.dumps(daily).encode()
    path.write_bytes(original)
    index = (tmp_path / "index.json").read_bytes()
    assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert path.read_bytes() == original
    assert (tmp_path / "index.json").read_bytes() == index


def test_command_can_disable_provider_thinking_when_explicitly_configured(tmp_path, monkeypatch):
    from collector import main

    def model(request):
        if request.get("thinking") != {"type": "disabled"}:
            return 400, b"thinking flag required by fixture"
        return 200, model_response([{"id": "2610.28637v1", "chinese_title": "配置成功", "chinese_summary": "示例摘要。", "brief_summary": "示例总结。"}])

    with service({"/list/cs/new": (200, listing_response("2610.28637v1")), "/v1/chat/completions": model}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("OPENAI_THINKING", "disabled")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["papers"][0]["translation"]["title"] == "配置成功"
    assert daily["stats"]["translated"] == 1


def test_command_adds_independent_rule_tags_without_a_jev_credential(tmp_path, monkeypatch):
    from collector import main

    feed = tagging_listing(
        {"title": "LLM-assisted experiments", "abstract": "Scientific tooling.", "categories": ["cs.SE", "cs.AI"]},
        {"title": "Agentic memory", "abstract": "Runtime controls."},
        {"title": "LLMs and Agents", "abstract": "Development studies.", "categories": ["cs.SE"]},
    )
    with service({"/list/cs/new": (200, feed)}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert [paper["tags"] for paper in daily["papers"]] == [["LLM", "软件工程"], ["Agent"], ["LLM", "Agent", "软件工程"]]
    for paper in daily["papers"]:
        assert paper["tagging"] == {
            "status": "fallback", "model": "jev-1.13.0", "rulesVersion": "daily-tags-v3",
            "threshold": 0.7, "inputSha256": paper["tagging"]["inputSha256"], "scores": {},
        }
        assert len(paper["tagging"]["inputSha256"]) == 64
    assert daily["stats"] == {"fetched": 3, "matched": 3, "translated": 0, "fallback": 3, "duplicates": 0}


@pytest.mark.parametrize("scores,expected", [
    ({"ai4s": 0.1, "codingagent": 0.96, "agentops": 0.7, "agentharness": 0.69, "enterprise_agent": 0.9},
     ["LLM", "Agent", "CodingAgent", "AgentOps", "软件工程", "企业Agent"]),
    ({"ai4s": 0, "codingagent": 0, "agentops": 0, "agentharness": 0, "enterprise_agent": 0},
     ["LLM", "Agent", "软件工程"]),
    ({"ai4s": 1, "codingagent": 1, "gui_agent": 1, "agentops": 1, "agentharness": 1, "enterprise_agent": 1},
     ["LLM", "Agent", "AI4S", "CodingAgent", "GUI Agent", "AgentOps", "AgentHarness", "软件工程", "企业Agent"]),
    ({"ai4s": 0, "codingagent": 0, "gui_agent": 0.7, "agentops": 0, "agentharness": 0, "enterprise_agent": 0},
     ["LLM", "Agent", "GUI Agent", "软件工程"]),
    ({"ai4s": 0, "codingagent": 0, "gui_agent": 0.69, "agentops": 0, "agentharness": 0, "enterprise_agent": 0},
     ["LLM", "Agent", "软件工程"]),
], ids=["mixed-and-threshold", "all-negative-is-success", "all-six", "gui-at-threshold", "gui-below-threshold"])
def test_command_adds_six_independent_jev_labels_even_when_translation_fails(tmp_path, monkeypatch, scores, expected):
    from collector import main

    submitted = []

    def jev(request):
        submitted.append(request)
        return 200, jev_response(scores)

    metadata = {"title": "LLM Agents for research", "abstract": "Original English input.", "categories": ["cs.SE"]}
    with service({"/list/cs/new": (200, tagging_listing(metadata)), "/typesafe/v1/systemone": jev,
                  "/v1/chat/completions": (503, b"translation temporarily unavailable")}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "translation-fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    paper = daily["papers"][0]
    assert paper["tags"] == expected
    assert paper["tagging"]["status"] == "tagged"
    assert paper["tagging"]["scores"] == {
        "AI4S": scores["ai4s"], "CodingAgent": scores["codingagent"], "AgentOps": scores["agentops"],
        "GUI Agent": scores.get("gui_agent", 0),
        "AgentHarness": scores["agentharness"], "企业Agent": scores["enterprise_agent"],
    }
    assert paper["translation"]["status"] == "fallback"
    assert len(submitted) == 1
    assert submitted[0]["model"] == "jev-1.13.0"
    assert json.loads(submitted[0]["state"]) == metadata
    assert set(submitted[0]["questions"]) == {"ai4s", "codingagent", "gui_agent", "agentops", "agentharness", "enterprise_agent"}
    assert all(question["type"] == "noul" and question["instructions"] for question in submitted[0]["questions"].values())


def test_command_reuses_tagged_papers_and_only_retries_failed_tagging_without_retranslation(tmp_path, monkeypatch):
    from collector import main

    titles = ["LLM Agent first", "LLM Agent retry"]
    translated = [{"id": f"2610.{position:05d}v1", "chinese_title": f"中文标题{position}",
                   "chinese_summary": "成功译文。", "brief_summary": "成功总结。"} for position in (1, 2)]

    def initial_jev(request):
        if json.loads(request["state"])["title"] == titles[1]:
            return 200, b'{"answers":{}}'
        return 200, jev_response({"ai4s": 0, "codingagent": 0, "agentops": 0, "agentharness": 0, "enterprise_agent": 0})

    with service({"/list/cs/new": (200, tagging_listing(*[{"title": title, "abstract": "English input."} for title in titles])),
                  "/typesafe/v1/systemone": initial_jev, "/v1/chat/completions": (200, model_response(translated))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "translation-fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    path = tmp_path / "2026-10-22.json"
    before = json.loads(path.read_text())
    assert [paper["tagging"]["status"] for paper in before["papers"]] == ["tagged", "fallback"]
    tagging_requests, translation_requests = [], []

    def retry_jev(request):
        tagging_requests.append(json.loads(request["state"])["title"])
        return 200, jev_response({"ai4s": 0, "codingagent": 0, "agentops": 1, "agentharness": 0, "enterprise_agent": 0})

    def unexpected_translation(request):
        translation_requests.append(request)
        return 503, b"must reuse translations"

    with service({"/list/cs/new": (503, b"must not fetch current source"), "/typesafe/v1/systemone": retry_jev,
                  "/v1/chat/completions": unexpected_translation}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)],
                    now=datetime.fromisoformat("2026-10-23T13:30:00+08:00")) == 0
    after = json.loads(path.read_text())
    assert tagging_requests == [titles[1]]
    assert translation_requests == []
    assert after["papers"][0] == before["papers"][0]
    assert after["papers"][1]["tags"] == ["LLM", "Agent", "AgentOps"]
    assert all(paper["tagging"]["status"] == "tagged" for paper in after["papers"])
    assert [paper["translation"] for paper in after["papers"]] == [paper["translation"] for paper in before["papers"]]
    assert (after["source"], after["fetchedAt"], after["stats"]) == (before["source"], before["fetchedAt"], before["stats"])
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["updatedAt"] == "2026-10-23T13:30:00+08:00"
    assert index["days"][0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_command_retries_a_transient_jev_error_before_archiving_success(tmp_path, monkeypatch):
    from collector import main

    calls = []

    def jev(request):
        calls.append(request)
        if len(calls) < 3:
            return 503, b"private provider body: tagging-fixture-not-a-secret"
        return 200, jev_response({"ai4s": 0, "codingagent": 1, "agentops": 0, "agentharness": 0, "enterprise_agent": 0})

    with service({"/list/cs/new": (200, listing_response("2610.28637v1")), "/typesafe/v1/systemone": jev}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert len(calls) == 3
    assert daily["papers"][0]["tagging"]["status"] == "tagged"
    assert daily["papers"][0]["tags"] == ["LLM", "CodingAgent"]


@pytest.mark.parametrize("status,expected_calls", [(401, 1), (402, 1), (403, 1), (429, 3)])
def test_command_stops_global_jev_failures_but_finishes_translation_and_safe_rule_tag_archive(tmp_path, monkeypatch, capsys, status, expected_calls):
    from collector import main

    tagging_requests, translation_requests = [], []

    def jev(request):
        tagging_requests.append(request)
        return status, b"private provider body: tagging-fixture-not-a-secret"

    def translate(request):
        translation_requests.append(request)
        return 200, model_response([{
            "id": f"2610.{position:05d}v1", "chinese_title": "成功标题", "chinese_summary": "成功摘要。", "brief_summary": "成功总结。"
        } for position in (1, 2, 3)])

    with service({"/list/cs/new": (200, tagging_listing(*[{"title": f"LLM Agent {position}", "abstract": "English input."} for position in (1, 2, 3)])),
                  "/typesafe/v1/systemone": jev, "/v1/chat/completions": translate}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "translation-fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    content = (tmp_path / "2026-10-22.json").read_text()
    daily = json.loads(content)
    assert len(tagging_requests) == expected_calls
    assert len(translation_requests) == 1
    assert daily["stats"] == {"fetched": 3, "matched": 3, "translated": 3, "fallback": 0, "duplicates": 0}
    assert all(paper["tags"] == ["LLM", "Agent"] and paper["tagging"]["status"] == "fallback" and paper["tagging"]["scores"] == {} for paper in daily["papers"])
    output = capsys.readouterr()
    assert "private provider body" not in content + output.out + output.err
    assert "fixture-not-a-secret" not in content + output.out + output.err


def test_command_archives_a_bulk_day_after_exhausted_jev_service_failures_without_losing_success(tmp_path, monkeypatch):
    from collector import main

    calls = []

    def jev(request):
        title = json.loads(request["state"])["title"]
        calls.append(title)
        if title == "LLM Agent 0":
            return 200, jev_response({"ai4s": 0, "codingagent": 1, "agentops": 0, "agentharness": 0, "enterprise_agent": 0})
        return 503, b"fixture service unavailable"

    feed = tagging_listing(*[{"title": f"LLM Agent {position}", "abstract": "English input."} for position in range(208)])
    with service({"/list/cs/new": (200, feed), "/typesafe/v1/systemone": jev}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        monkeypatch.setenv("JEV_WORKERS", "1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert calls == ["LLM Agent 0", "LLM Agent 1", "LLM Agent 1", "LLM Agent 1"]
    assert daily["stats"] == {"fetched": 208, "matched": 208, "translated": 0, "fallback": 208, "duplicates": 0}
    assert daily["papers"][0]["tags"] == ["LLM", "Agent", "CodingAgent"]
    assert daily["papers"][0]["tagging"]["status"] == "tagged"
    assert all(paper["tags"] == ["LLM", "Agent"] and paper["tagging"]["status"] == "fallback"
               and paper["tagging"]["scores"] == {} for paper in daily["papers"][1:])
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["days"][0]["count"] == 208
    assert index["days"][0]["sha256"] == hashlib.sha256((tmp_path / "2026-10-22.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["model", "rulesVersion", "threshold", "title", "abstract", "categories"])
def test_command_invalidates_successful_tag_cache_when_configuration_or_english_input_changes(tmp_path, monkeypatch, change):
    from collector import main

    calls = []

    def jev(request):
        calls.append(request)
        return 200, jev_response({"ai4s": 0, "codingagent": 0.8, "agentops": 0, "agentharness": 0, "enterprise_agent": 0})

    metadata = {"title": "LLM Agent original", "abstract": "Original input.", "categories": ["cs.AI"]}
    path = tmp_path / "2026-10-22.json"
    with service({"/list/cs/new": (200, tagging_listing(metadata)), "/typesafe/v1/systemone": jev}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        if change == "rulesVersion":
            monkeypatch.setenv("JEV_RULES_VERSION", "daily-tags-v2")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
        before = json.loads(path.read_text())
        assert len(calls) == 1
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
        assert len(calls) == 1
        if change == "rulesVersion":
            monkeypatch.delenv("JEV_RULES_VERSION")
        elif change in {"model", "threshold"}:
            name, value = {"model": ("JEV_MODEL", "jev-1.14.0"),
                           "threshold": ("JEV_THRESHOLD", "0.9")}[change]
            monkeypatch.setenv(name, value)
        else:
            changed = deepcopy(before)
            paper = changed["papers"][0]
            if change == "categories":
                paper["categories"].append("cs.SE")
            else:
                paper[change] += " Changed English input."
                paper["translation"][change] = paper[change]
            path.write_text(json.dumps(changed))
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
        assert len(calls) == 2
        after = json.loads(path.read_text())
        tagging = after["papers"][0]["tagging"]
        assert tagging["status"] == "tagged"
        if change in {"title", "abstract", "categories"}:
            assert tagging["inputSha256"] != before["papers"][0]["tagging"]["inputSha256"]
        elif change == "threshold":
            assert tagging["threshold"] == 0.9
            assert "CodingAgent" not in after["papers"][0]["tags"]
        elif change == "model":
            assert tagging["model"] == "jev-1.14.0" and calls[-1]["model"] == "jev-1.14.0"
        else:
            assert before["papers"][0]["tagging"]["rulesVersion"] == "daily-tags-v2"
            assert tagging["rulesVersion"] == "daily-tags-v3"
        # Cached valid results also remain available if a later run has no API key.
        monkeypatch.delenv("JEV_API_KEY")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
        assert json.loads(path.read_text())["papers"] == after["papers"]


def test_command_backfills_legacy_untagged_archive_without_fetching_or_retranslating(tmp_path, monkeypatch):
    from collector import main

    with service({"/list/cs/new": (200, listing_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    path = tmp_path / "2026-10-22.json"
    legacy = json.loads(path.read_text())
    paper = legacy["papers"][0]
    paper.pop("tags")
    paper.pop("tagging")
    paper["translation"] = {"status": "translated", "title": "已有标题", "abstract": "已有摘要。", "brief": "已有总结。"}
    legacy["stats"].update(translated=1, fallback=0)
    path.write_text(json.dumps(legacy))
    requests = []

    def jev(request):
        requests.append(request)
        return 200, jev_response({"ai4s": 0, "codingagent": 0, "agentops": 0, "agentharness": 0, "enterprise_agent": 0})

    with service({"/list/cs/new": (503, b"must not fetch"), "/v1/chat/completions": (503, b"must not translate"),
                  "/typesafe/v1/systemone": jev}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "translation-fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)],
                    now=datetime.fromisoformat("2026-10-23T13:30:00+08:00")) == 0
    daily = json.loads(path.read_text())
    assert len(requests) == 1
    assert daily["papers"][0]["tagging"]["status"] == "tagged"
    assert daily["papers"][0]["tags"] == ["LLM"]
    assert daily["papers"][0]["translation"] == legacy["papers"][0]["translation"]
    assert (daily["source"], daily["fetchedAt"], daily["stats"]) == (legacy["source"], legacy["fetchedAt"], legacy["stats"])


def test_command_never_implicitly_uses_translation_credentials_for_jev(tmp_path, monkeypatch):
    from collector import main

    requests = []

    def unexpected_jev(request):
        requests.append(request)
        return 403, b"must not share implicit credentials"

    with service({"/list/cs/new": (200, listing_response("2610.28637v1")), "/typesafe/v1/systemone": unexpected_jev,
                  "/v1/chat/completions": (200, model_response([{"id": "2610.28637v1", "chinese_title": "成功标题",
                                                               "chinese_summary": "成功摘要。", "brief_summary": "成功总结。"}]))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "translation-fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    paper = json.loads((tmp_path / "2026-10-22.json").read_text())["papers"][0]
    assert requests == []
    assert paper["translation"]["status"] == "translated"
    assert paper["tagging"]["status"] == "fallback"
    assert paper["tags"] == ["LLM"]


@pytest.mark.parametrize("defect", ["invalid-json", "missing-answer", "extra-answer", "wrong-type", "boolean", "string", "nan", "infinite", "negative", "too-large"])
def test_command_does_not_mark_malformed_jev_responses_as_success_or_publish_provider_details(tmp_path, monkeypatch, capsys, defect):
    from collector import main

    response = json.loads(jev_response({"ai4s": 0, "codingagent": 0, "agentops": 0, "agentharness": 0, "enterprise_agent": 0}))
    response["private"] = "private provider body: tagging-fixture-not-a-secret"
    if defect == "missing-answer": del response["answers"]["agentops"]
    elif defect == "extra-answer": response["answers"]["unknown"] = {"type": "noul", "noul": 1}
    elif defect == "wrong-type": response["answers"]["agentops"]["type"] = "text"
    elif defect != "invalid-json":
        response["answers"]["agentops"]["noul"] = {"boolean": True, "string": "0.9", "nan": float("nan"),
                                                    "infinite": float("inf"), "negative": -0.1, "too-large": 1.1}[defect]
    body = b"private provider body: tagging-fixture-not-a-secret" if defect == "invalid-json" else json.dumps(response).encode()
    calls = []

    def jev(request):
        calls.append(request)
        return 200, body

    with service({"/list/cs/new": (200, listing_response("2610.28637v1")), "/typesafe/v1/systemone": jev}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    content = (tmp_path / "2026-10-22.json").read_text()
    paper = json.loads(content)["papers"][0]
    assert len(calls) == 1
    assert paper["tagging"]["status"] == "fallback"
    assert paper["tagging"]["scores"] == {}
    assert paper["tags"] == ["LLM"]
    output = capsys.readouterr()
    assert "private provider body" not in content + output.out + output.err
    assert "fixture-not-a-secret" not in content + output.out + output.err


def test_command_honors_the_jev_concurrency_limit_after_the_initial_health_request(tmp_path, monkeypatch):
    from collector import main

    lock, simultaneous = Lock(), Event()
    state = {"active": 0, "peak": 0, "calls": 0}
    response = jev_response({"ai4s": 0, "codingagent": 0, "agentops": 0, "agentharness": 0, "enterprise_agent": 0})

    def jev(request):
        with lock:
            state["calls"] += 1
            if json.loads(request["state"])["title"] == "LLM Agent 0":
                return 200, response
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            if state["active"] == 2:
                simultaneous.set()
        simultaneous.wait(3)
        with lock:
            state["active"] -= 1
        return 200, response

    feed = tagging_listing(*[{"title": f"LLM Agent {position}", "abstract": "English input."} for position in range(5)])
    with service({"/list/cs/new": (200, feed), "/typesafe/v1/systemone": jev}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("JEV_API_KEY", "tagging-fixture-not-a-secret")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        monkeypatch.setenv("JEV_WORKERS", "2")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    papers = json.loads((tmp_path / "2026-10-22.json").read_text())["papers"]
    assert state["peak"] == 2 and state["calls"] == 5
    assert all(paper["tagging"]["status"] == "tagged" for paper in papers)
