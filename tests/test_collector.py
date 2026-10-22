"""Exercise the supported collector command against external HTTP fixtures."""

from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import xml.etree.ElementTree as ET

import pytest


FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime.fromisoformat("2026-10-22T13:30:00+08:00")


@pytest.fixture(autouse=True)
def fixture_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_THINKING", raising=False)
    monkeypatch.setenv("ARXIV_RETRY_DELAY_SECONDS", "0")


def rss_response(*ids):
    root = ET.parse(FIXTURES / "rss-selected.xml").getroot()
    channel = root.find("channel")
    for item in channel.findall("item"):
        if item.findtext("guid").removeprefix("oai:arXiv.org:") not in ids:
            channel.remove(item)
    return ET.tostring(root)


def model_response(translations):
    return json.dumps({"choices": [{"message": {"content": json.dumps({"translations": translations}, ensure_ascii=False)}}]}).encode()


@contextmanager
def service(routes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = routes[self.path]
            status, body = route() if callable(route) else route
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            route = routes[self.path]
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
    with service({"/rss/cs": (200, rss_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert (daily["schemaVersion"], daily["date"], daily["timezone"], daily["fetchedAt"]) == (
        1, "2026-10-22", "Asia/Shanghai", "2026-10-22T13:30:00+08:00"
    )
    assert daily["source"]["updatedAt"] == "2026-10-22T00:00:00-04:00"
    assert daily["stats"] == {"fetched": 1, "matched": 1, "translated": 0, "fallback": 1}
    paper = daily["papers"][0]
    assert (paper["id"], paper["authors"], paper["categories"], paper["announceType"]) == (
        "2610.28637v1", ["Dong Liu", "Yanxuan Yu", "Eric Jiang", "Shu Wang", "Ying Nian Wu"],
        ["cs.LG", "cs.DC"], "new"
    )
    assert paper["primaryCategory"] == ""
    assert paper["affiliations"] == []
    assert paper["updatedAt"] is None
    assert paper["publishedAt"] == "2026-10-22T00:00:00-04:00"
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


def test_command_keeps_all_revision_types_but_applies_original_topic_and_category_rules(tmp_path, monkeypatch):
    from collector import main

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with service({"/rss/cs": (200, (FIXTURES / "rss-selected.xml").read_bytes())}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert [(paper["id"], paper["announceType"]) for paper in daily["papers"]] == [
        ("2610.28637v1", "new"), ("2609.00755v1", "cross"),
        ("2106.06060v5", "replace"), ("2608.15900v2", "replace-cross"),
    ]
    assert daily["stats"] == {"fetched": 7, "matched": 4, "translated": 0, "fallback": 4}


def test_command_publishes_compatible_model_translation_without_losing_originals(tmp_path, monkeypatch):
    from collector import main

    model_response = {"choices": [{"message": {"content": json.dumps({"translations": [{
        "id": "2610.28637v1", "chinese_title": "缓存保留研究", "chinese_summary": "示例译文。", "brief_summary": "针对缓存问题，通过学习方法选择保留内容。"
    }]}, ensure_ascii=False)}}]}
    with service({
        "/rss/cs": (200, rss_response("2610.28637v1")),
        "/v1/chat/completions": (200, json.dumps(model_response).encode()),
    }) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("OPENAI_MODEL", "fixture-model")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["papers"][0]["translation"] == {
        "status": "translated", "title": "缓存保留研究", "abstract": "示例译文。", "brief": "针对缓存问题，通过学习方法选择保留内容。"
    }
    assert daily["papers"][0]["abstract"].startswith("Disaggregated")
    assert daily["stats"] == {"fetched": 1, "matched": 1, "translated": 1, "fallback": 0}


def test_command_replays_archived_day_without_fetching_current_feed_or_retranslating_success(tmp_path, monkeypatch):
    from collector import main

    first_translation = {"id": "2610.28637v1", "chinese_title": "已成功标题", "chinese_summary": "已成功摘要。", "brief_summary": "已成功总结。"}
    retry_translation = {"id": "2106.06060v5", "chinese_title": "补译标题", "chinese_summary": "补译摘要。", "brief_summary": "补译总结。"}
    with service({"/rss/cs": (200, rss_response("2610.28637v1", "2106.06060v5")), "/v1/chat/completions": (200, model_response([first_translation]))}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    def retry_model(request):
        submitted = json.loads(request["messages"][1]["content"].split("论文资料：\n", 1)[1])
        if [paper["id"] for paper in submitted] != ["2106.06060v5"]:
            return 400, b"unexpected repeat translation"
        return 200, model_response([retry_translation])

    with service({"/rss/cs": (503, b"unavailable"), "/v1/chat/completions": retry_model}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)], now=datetime.fromisoformat("2026-10-23T13:30:00+08:00")) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["source"]["url"] != origin + "/rss/cs"
    assert daily["fetchedAt"] == "2026-10-22T13:30:00+08:00"
    assert daily["source"]["updatedAt"] == "2026-10-22T00:00:00-04:00"
    assert json.loads((tmp_path / "index.json").read_text())["updatedAt"] == "2026-10-23T13:30:00+08:00"
    assert [(paper["translation"]["status"], paper["translation"]["title"]) for paper in daily["papers"]] == [("translated", "已成功标题"), ("translated", "补译标题")]
    assert daily["stats"] == {"fetched": 2, "matched": 2, "translated": 2, "fallback": 0}


def test_command_refuses_to_label_the_current_feed_as_missing_history(tmp_path, monkeypatch):
    from collector import main

    with service({"/rss/cs": (200, rss_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--date", "2026-10-21", "--output-dir", str(tmp_path)], now=NOW) == 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("batch_date,exit_code", [("22 Oct 2026", 0), ("21 Oct 2026", 1)])
def test_command_archives_zero_only_when_the_empty_batch_belongs_to_today(tmp_path, monkeypatch, batch_date, exit_code):
    from collector import main

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    content = (FIXTURES / "rss-empty.xml").read_bytes().replace(b"22 Oct 2026", batch_date.encode())
    with service({"/rss/cs": (200, content)}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == exit_code
    if exit_code:
        assert list(tmp_path.iterdir()) == []
    else:
        daily = json.loads((tmp_path / "2026-10-22.json").read_text())
        assert daily["papers"] == []
        assert daily["stats"] == {"fetched": 0, "matched": 0, "translated": 0, "fallback": 0}
        assert json.loads((tmp_path / "index.json").read_text())["days"][0]["count"] == 0


@pytest.mark.parametrize("response", [
    b"<rss><channel>",
    b"<html><body>rate limit</body></html>",
    b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>error</id></entry></feed>',
    rss_response("2610.28637v1").replace(b"<title>To Keep or Not to Keep: Learning KV Cache Retention in Disaggregated LLM Serving Systems</title>", b"<title/>"),
    rss_response("2610.28637v1").replace(b"<category>cs.LG</category>", b"").replace(b"<category>cs.DC</category>", b""),
], ids=["truncated-xml", "html-challenge", "atom-error", "missing-title", "missing-categories"])
def test_command_rejects_invalid_source_without_changing_the_last_valid_index(tmp_path, monkeypatch, response):
    from collector import main

    previous = b'{"schemaVersion":1,"updatedAt":null,"days":[]}\n'
    (tmp_path / "index.json").write_bytes(previous)
    with service({"/rss/cs": (200, response)}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert (tmp_path / "index.json").read_bytes() == previous
    assert not (tmp_path / "2026-10-22.json").exists()


def test_command_retries_a_transient_source_limit_then_archives_the_complete_batch(tmp_path, monkeypatch):
    from collector import main

    responses = iter([(429, b"temporarily limited"), (200, rss_response("2610.28637v1"))])
    with service({"/rss/cs": lambda: next(responses)}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        monkeypatch.setenv("ARXIV_RETRY_DELAY_SECONDS", "0")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    assert json.loads((tmp_path / "2026-10-22.json").read_text())["stats"]["matched"] == 1


def test_command_splits_a_possibly_truncated_archive_feed_into_complete_categories(tmp_path, monkeypatch):
    from collector import main

    from copy import deepcopy
    root = ET.fromstring(rss_response("2610.28637v1"))
    channel = root.find("channel")
    item = channel.find("item")
    for _ in range(1999):
        channel.append(deepcopy(item))
    categories = json.loads((Path(__file__).parents[1] / "collector/categories.json").read_text())["categories"]
    routes = {f"/rss/{category['code']}": (200, (FIXTURES / "rss-empty.xml").read_bytes()) for category in categories if category["enabled"]}
    routes["/rss/cs"] = (200, ET.tostring(root))
    routes["/rss/cs.LG"] = (200, rss_response("2610.28637v1"))
    with service(routes) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert [paper["id"] for paper in daily["papers"]] == ["2610.28637v1"]
    assert daily["stats"]["fetched"] == 1


@pytest.mark.parametrize("status,response", [
    (402, b'private provider body: fixture-not-a-secret'),
    (429, b'private provider body: fixture-not-a-secret'),
    (200, b'{"choices":[]}'),
    (200, model_response([{"id": "2610.28637v1", "chinese_title": "missing fields"}])),
], ids=["balance", "rate-limit", "invalid-response", "incomplete-translation"])
def test_translation_failures_keep_complete_english_without_publishing_provider_details(tmp_path, monkeypatch, capsys, status, response):
    from collector import main

    with service({"/rss/cs": (200, rss_response("2610.28637v1")), "/v1/chat/completions": (status, response)}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
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
    with service({"/rss/cs": (503, b'private upstream response')}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert (tmp_path / "index.json").read_bytes() == previous
    assert not (tmp_path / "2026-10-22.json").exists()
    error = capsys.readouterr().err
    assert "HTTP 503" in error
    assert "private upstream response" not in error


@pytest.mark.parametrize("defect", ["wrong-date", "wrong-schema", "unknown-translation-state", "missing-translation-title"])
def test_command_does_not_overwrite_an_invalid_archived_source(tmp_path, monkeypatch, defect):
    from collector import main

    with service({"/rss/cs": (200, rss_response("2610.28637v1"))}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
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


def test_command_refuses_a_category_that_still_reaches_the_source_limit(tmp_path, monkeypatch):
    from collector import main
    from copy import deepcopy

    root = ET.fromstring(rss_response("2610.28637v1"))
    channel = root.find("channel")
    item = channel.find("item")
    for _ in range(1999):
        channel.append(deepcopy(item))
    capped = ET.tostring(root)
    with service({"/rss/cs": (200, capped), "/rss/cs.AI": (200, capped)}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert list(tmp_path.iterdir()) == []


def test_command_deduplicates_only_identical_versions_in_the_current_batch(tmp_path, monkeypatch):
    from collector import main
    from copy import deepcopy

    root = ET.fromstring(rss_response("2610.28637v1"))
    channel = root.find("channel")
    item = channel.find("item")
    channel.append(deepcopy(item))
    version_two = deepcopy(item)
    version_two.find("guid").text = "oai:arXiv.org:2610.28637v2"
    channel.append(version_two)
    with service({"/rss/cs": (200, ET.tostring(root))}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert [paper["id"] for paper in daily["papers"]] == ["2610.28637v1", "2610.28637v2"]


def test_command_can_disable_provider_thinking_when_explicitly_configured(tmp_path, monkeypatch):
    from collector import main

    def model(request):
        if request.get("thinking") != {"type": "disabled"}:
            return 400, b"thinking flag required by fixture"
        return 200, model_response([{"id": "2610.28637v1", "chinese_title": "配置成功", "chinese_summary": "示例摘要。", "brief_summary": "示例总结。"}])

    with service({"/rss/cs": (200, rss_response("2610.28637v1")), "/v1/chat/completions": model}) as origin:
        monkeypatch.setenv("ARXIV_FEED_URL", origin + "/rss/cs")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-not-a-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("OPENAI_THINKING", "disabled")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert daily["papers"][0]["translation"]["title"] == "配置成功"
    assert daily["stats"]["translated"] == 1
