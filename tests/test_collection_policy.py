"""Verify daily admission and normal weekend outcomes through public commands."""

from datetime import datetime
import hashlib
import json
import os

import pytest

from listing_fixtures import LIST_PATH, listing_page, selected_entries
from test_collector import NOW, jev_response, model_response, service
from test_publish import archive


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("OPENAI_", "JEV_", "ARXIV_", "TRANSLATION_", "OSS_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARXIV_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("ARXIV_RETRY_DELAY_SECONDS", "0")
    monkeypatch.setenv("ARXIV_PAGE_DELAY_SECONDS", "0")
    monkeypatch.setenv("JEV_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("JEV_RETRY_DELAY_SECONDS", "0")


def past_paper(identifier):
    return {
        "id": identifier, "title": "Agent research", "abstract": "An original agent study.",
        "authors": ["Researcher"], "affiliations": [], "categories": ["cs.AI"], "primaryCategory": "cs.AI",
        "publishedAt": "2026-10-15T00:00:00-04:00", "updatedAt": None, "announceType": "new",
        "absUrl": f"https://arxiv.org/abs/{identifier}", "pdfUrl": f"https://arxiv.org/pdf/{identifier}",
        "htmlUrl": f"https://arxiv.org/html/{identifier}",
        "translation": {"status": "fallback", "title": "Agent research", "abstract": "An original agent study.", "brief": ""},
    }


@pytest.mark.parametrize(("clock", "day", "fetched_at"), [
    ("2026-10-23T16:30:00+00:00", "2026-10-24", "2026-10-24T00:30:00+08:00"),
    ("2026-10-25T15:59:00+00:00", "2026-10-25", "2026-10-25T23:59:00+08:00"),
])
def test_beijing_weekend_succeeds_without_source_or_model_requests(tmp_path, monkeypatch, clock, day, fetched_at):
    from collector import main
    from collector.publish import main as publish

    requests = []

    def unexpected(*_args):
        requests.append(True)
        return 503, b"weekend needs no upstream service"

    with service({LIST_PATH: unexpected, "/v1/chat/completions": unexpected,
                  "/typesafe/v1/systemone": unexpected}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "fixture-only")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        monkeypatch.setenv("JEV_THRESHOLD", "unused-on-weekends")
        now = datetime.fromisoformat(clock)
        assert main(["--output-dir", str(tmp_path)], now=now) == 0

    assert requests == []
    daily = json.loads((tmp_path / f"{day}.json").read_text())
    assert daily["source"] == {
        "kind": "announcement-schedule",
        "url": "https://info.arxiv.org/help/availability.html#announcement-schedule",
        "reason": "weekend", "updatedAt": None,
    }
    assert daily["fetchedAt"] == fetched_at
    assert daily["papers"] == []
    assert daily["stats"] == {"fetched": 0, "matched": 0, "translated": 0, "fallback": 0, "duplicates": 0}
    assert publish(["--date", day, "--data-dir", str(tmp_path), "--check"]) == 0


def test_duplicate_filtering_precedes_models_and_replay_reuses_successes(tmp_path, monkeypatch):
    from collector import main

    archive(tmp_path, "2026-10-15", papers=[past_paper("2610.28637v2")])
    previous_bytes = (tmp_path / "2026-10-15.json").read_bytes()
    current = selected_entries("2610.28637v1", "2610.29003v1")
    current[0]["id"] = "2610.28637"
    translated_ids, tagged_inputs = [], []

    def translate(request):
        batch = json.loads(request["messages"][1]["content"].split("论文资料：\n", 1)[1])
        translated_ids.extend(paper["id"] for paper in batch)
        return 200, model_response([{"id": "2610.29003v1", "chinese_title": "新论文",
                                    "chinese_summary": "摘要", "brief_summary": "总结"}])

    def tag(request):
        tagged_inputs.append(json.loads(request["state"]))
        return 200, jev_response({"ai4s": 0, "codingagent": 0, "agentops": 0, "agentharness": 0, "enterprise_agent": 0})

    with service({LIST_PATH: (200, listing_page(current)), "/v1/chat/completions": translate,
                  "/typesafe/v1/systemone": tag}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "fixture-only")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0

    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert [paper["id"] for paper in daily["papers"]] == ["2610.29003v1"]
    assert daily["stats"] == {"fetched": 2, "matched": 1, "translated": 1, "fallback": 0, "duplicates": 1}
    assert translated_ids == ["2610.29003v1"]
    assert [value["title"] for value in tagged_inputs] == [current[1]["title"]]
    assert (tmp_path / "2026-10-15.json").read_bytes() == previous_bytes

    completed = (tmp_path / "2026-10-22.json").read_bytes()
    (tmp_path / "2026-10-21.json").write_text("unreadable history must not block an existing-day replay")
    replay_requests = []

    def unexpected(*_args):
        replay_requests.append(True)
        return 503, b"a completed archive must reuse successful results"

    with service({LIST_PATH: unexpected, "/v1/chat/completions": unexpected,
                  "/typesafe/v1/systemone": unexpected}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        for clock in [NOW, datetime.fromisoformat("2026-10-24T13:30:00+08:00")]:
            assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)], now=clock) == 0
    assert replay_requests == []
    assert (tmp_path / "2026-10-22.json").read_bytes() == completed


@pytest.mark.parametrize("duplicates", [None, 0, 2])
def test_legacy_replay_preserves_optional_duplicate_statistics(tmp_path, monkeypatch, duplicates):
    from collector import main
    from collector.publish import main as publish

    archive(tmp_path)
    path = tmp_path / "2026-10-22.json"
    expected = json.loads(path.read_text())
    if duplicates is not None:
        expected["stats"].update(fetched=duplicates, duplicates=duplicates)
    path.write_text(json.dumps(expected, indent=2) + "\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path = tmp_path / "index.json"
    index = json.loads(index_path.read_text())
    index["days"][0].update(sha256=digest, file=f"2026-10-22/{digest}.json")
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    assert publish(["--date", "2026-10-22", "--data-dir", str(tmp_path), "--check"]) == 0

    monkeypatch.setenv("ARXIV_LIST_URL", "invalid-but-unused")
    assert main(["--date", "2026-10-22", "--output-dir", str(tmp_path)], now=NOW) == 0
    assert json.loads(path.read_text()) == expected
    assert publish(["--date", "2026-10-22", "--data-dir", str(tmp_path), "--check"]) == 0


def test_all_recent_duplicates_fail_without_models_or_index_changes(tmp_path, monkeypatch, capsys):
    from collector import main

    archive(tmp_path, "2026-10-21", papers=[past_paper("2610.28637v2")])
    previous_index = (tmp_path / "index.json").read_bytes()
    requests = []

    def unexpected(request):
        requests.append(request)
        return 503, b"do not pay to process duplicate papers"

    with service({LIST_PATH: (200, listing_page(selected_entries("2610.28637v1"))),
                  "/v1/chat/completions": unexpected, "/typesafe/v1/systemone": unexpected}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "fixture-only")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1

    assert requests == []
    assert not (tmp_path / "2026-10-22.json").exists()
    assert (tmp_path / "index.json").read_bytes() == previous_index
    assert "already archived" in capsys.readouterr().err


def test_older_than_seven_dates_is_not_read_or_used_to_fill_missing_days(tmp_path, monkeypatch):
    from collector import main

    archive(tmp_path, "2026-10-14", papers=[past_paper("2610.28637v2")])
    # Reading all history, or trying to obtain seven nonempty days, would fail here.
    (tmp_path / "2026-10-13.json").write_text("not a daily archive")
    with service({LIST_PATH: (200, listing_page(selected_entries("2610.28637v1")))}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 0
    daily = json.loads((tmp_path / "2026-10-22.json").read_text())
    assert [paper["id"] for paper in daily["papers"]] == ["2610.28637v1"]
    assert daily["stats"]["duplicates"] == 0


@pytest.mark.parametrize("historical_content", ["not JSON", '{"date":"2026-10-21","papers":[]}'])
def test_corrupt_existing_recent_archive_fails_before_models(tmp_path, monkeypatch, historical_content):
    from collector import main

    (tmp_path / "2026-10-21.json").write_text(historical_content)
    previous_index = b'{"schemaVersion":1,"updatedAt":null,"days":[]}\n'
    (tmp_path / "index.json").write_bytes(previous_index)
    requests = []

    def model(request):
        requests.append(request)
        return 503, b"must reject unreadable history first"

    with service({LIST_PATH: (200, listing_page(selected_entries("2610.28637v1"))),
                  "/v1/chat/completions": model, "/typesafe/v1/systemone": model}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-only")
        monkeypatch.setenv("OPENAI_BASE_URL", origin + "/v1")
        monkeypatch.setenv("JEV_API_KEY", "fixture-only")
        monkeypatch.setenv("JEV_BASE_URL", origin + "/typesafe/v1")
        assert main(["--output-dir", str(tmp_path)], now=NOW) == 1
    assert requests == []
    assert not (tmp_path / "2026-10-22.json").exists()
    assert (tmp_path / "index.json").read_bytes() == previous_index


@pytest.mark.parametrize(("clock", "day"), [
    ("2026-10-23T15:59:00+00:00", "2026-10-23"),
    ("2026-10-25T16:00:00+00:00", "2026-10-26"),
])
def test_beijing_weekdays_at_weekend_boundaries_still_require_source(tmp_path, monkeypatch, clock, day):
    from collector import main

    requests = []

    def unavailable():
        requests.append(True)
        return 503, b"weekday batch unavailable"

    with service({LIST_PATH: unavailable}) as origin:
        monkeypatch.setenv("ARXIV_LIST_URL", origin + "/list/cs/new")
        assert main(["--output-dir", str(tmp_path)], now=datetime.fromisoformat(clock)) == 1
    assert requests == [True]
    assert not (tmp_path / f"{day}.json").exists()
    assert not (tmp_path / "index.json").exists()


def test_an_absent_historical_weekend_is_not_backfilled(tmp_path, monkeypatch):
    from collector import main

    monkeypatch.setenv("ARXIV_LIST_URL", "invalid-but-unused")
    assert main(["--date", "2026-10-24", "--output-dir", str(tmp_path)],
                now=datetime.fromisoformat("2026-10-25T13:30:00+08:00")) == 1
    assert not list(tmp_path.iterdir())


def test_weekend_zero_uses_the_existing_verified_oss_publication_flow(tmp_path, monkeypatch):
    from collector import main
    from collector.publish import main as publish
    from test_publish import PREFIX, configure, object_service

    monkeypatch.setenv("ARXIV_LIST_URL", "unused-on-weekends")
    assert main(["--output-dir", str(tmp_path)],
                now=datetime.fromisoformat("2026-10-24T13:30:00+08:00")) == 0
    content = (tmp_path / "2026-10-24.json").read_bytes()
    index = json.loads((tmp_path / "index.json").read_text())
    entry = index["days"][0]
    assert entry["count"] == 0
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert publish(["--date", "2026-10-24", "--data-dir", str(tmp_path)]) == 0
        assert state["objects"][PREFIX + "/" + entry["file"]] == content
        assert state["objects"][PREFIX + "/index.json"] == (tmp_path / "index.json").read_bytes()
        assert PREFIX + "/" + entry["file"] in state["verified"]
