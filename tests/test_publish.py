"""Exercise the supported publisher command through an OSS-compatible HTTP boundary."""

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

import pytest


PREFIX = "research/arxiv-daily"
DAY = "2026-10-22"


def archive(data_dir, day=DAY, *, papers=()):
    translated = sum(paper.get("translation", {}).get("status") == "translated" for paper in papers)
    daily = {
        "schemaVersion": 1, "date": day, "timezone": "Asia/Shanghai",
        "fetchedAt": f"{day}T13:30:00+08:00",
        "source": {"url": "https://rss.arxiv.org/rss/cs", "updatedAt": f"{day}T00:00:00-04:00"},
        "stats": {"fetched": len(papers), "matched": len(papers), "translated": translated, "fallback": len(papers) - translated},
        "papers": list(papers),
    }
    content = (json.dumps(daily, indent=2) + "\n").encode()
    (data_dir / f"{day}.json").write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    entry = {"date": day, "count": len(papers), "sha256": digest, "file": f"{day}/{digest}.json"}
    index_path = data_dir / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"schemaVersion": 1, "days": []}
    index["updatedAt"] = daily["fetchedAt"]
    index["days"] = sorted(index["days"] + [entry], key=lambda value: value["date"], reverse=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    return entry, content


@contextmanager
def object_service():
    objects, metadata, verified = {}, {}, set()
    state = {"objects": objects, "metadata": metadata, "verified": verified}

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            key = unquote(urlsplit(self.path).path).removeprefix("/fixture-bucket/")
            content = self.rfile.read(int(self.headers["Content-Length"]))
            if key == state.get("fail_upload"):
                self.respond(503, b"<Error><Code>Unavailable</Code><Message>private fixture-not-a-secret</Message></Error>")
                return
            if key == PREFIX + "/index.json":
                index = json.loads(content)
                if any(PREFIX + "/" + entry["file"] not in verified for entry in index["days"]):
                    self.respond(409, b"<Error><Code>UnverifiedDay</Code></Error>")
                    return
            if self.headers.get("x-oss-forbid-overwrite") == "true" and key in objects:
                self.respond(409, b"<Error><Code>FileAlreadyExists</Code></Error>")
                return
            objects[key] = content
            metadata[key] = {key.lower(): value for key, value in self.headers.items()}
            self.respond(200, b"")

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            key = path.removeprefix("/fixture-bucket/") if path.startswith("/fixture-bucket/") else path.lstrip("/")
            if key not in objects:
                self.respond(404, b"<Error><Code>NoSuchKey</Code></Error>")
                return
            if not self.headers.get("Authorization"):
                verified.add(key)
                if key == state.get("corrupt_public"):
                    self.respond(200, b"corrupt bytes")
                    return
                if key == PREFIX + "/index.json" and state.pop("corrupt_index_once", False):
                    self.respond(200, b"cached or corrupt index")
                    return
            self.respond(200, objects[key], metadata.get(key, {}))

        def respond(self, status, body, headers=None):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                if key in {"content-type", "cache-control", "x-oss-meta-sha256"}:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def configure(monkeypatch, origin):
    monkeypatch.setenv("OSS_ACCESS_KEY_ID", "fixture-id")
    monkeypatch.setenv("OSS_ACCESS_KEY_SECRET", "fixture-not-a-secret")
    monkeypatch.setenv("OSS_ENDPOINT", origin)
    monkeypatch.setenv("OSS_BUCKET", "fixture-bucket")
    monkeypatch.setenv("OSS_PREFIX", PREFIX)
    monkeypatch.setenv("OSS_PUBLIC_BASE_URL", origin)


def test_command_serves_identical_immutable_day_bytes_before_publishing_the_short_cache_index(tmp_path, monkeypatch):
    from collector.publish import main

    entry, content = archive(tmp_path)
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 0
        with urlopen(origin + "/" + PREFIX + "/" + entry["file"]) as response:
            assert response.read() == content
            assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
            assert response.headers["Content-Type"] == "application/json; charset=utf-8"
        with urlopen(origin + "/" + PREFIX + "/index.json") as response:
            assert response.read() == (tmp_path / "index.json").read_bytes()
            assert response.headers["Cache-Control"] == "public, max-age=60, must-revalidate"
        assert all(value["x-oss-object-acl"] == "public-read" for value in state["metadata"].values())
        assert state["metadata"][PREFIX + "/" + entry["file"]]["x-oss-forbid-overwrite"] == "true"


def test_command_reuses_an_already_uploaded_day_on_a_same_day_rerun(tmp_path, monkeypatch):
    from collector.publish import main

    entry, content = archive(tmp_path)
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 0
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 0
        with urlopen(origin + "/" + PREFIX + "/" + entry["file"]) as response:
            assert response.read() == content


def test_command_recovers_earlier_git_backups_before_exposing_a_multi_day_index(tmp_path, monkeypatch):
    from collector.publish import main

    earlier, earlier_content = archive(tmp_path, "2026-10-21")
    latest, latest_content = archive(tmp_path)
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 0
        with urlopen(origin + "/" + PREFIX + "/index.json") as response:
            assert [day["date"] for day in json.load(response)["days"]] == ["2026-10-22", "2026-10-21"]
        for entry, content in ((earlier, earlier_content), (latest, latest_content)):
            with urlopen(origin + "/" + PREFIX + "/" + entry["file"]) as response:
                assert response.read() == content


def test_command_restores_the_previous_index_if_new_index_public_verification_fails(tmp_path, monkeypatch):
    from collector.publish import main

    archive(tmp_path, "2026-10-21")
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert main(["--date", "2026-10-21", "--data-dir", str(tmp_path)]) == 0
        with urlopen(origin + "/" + PREFIX + "/index.json") as response:
            previous = response.read()
        archive(tmp_path)
        local_index = (tmp_path / "index.json").read_bytes()
        state["corrupt_index_once"] = True
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 1
        with urlopen(origin + "/" + PREFIX + "/index.json") as response:
            assert response.read() == previous
        assert (tmp_path / "index.json").read_bytes() == local_index


@pytest.mark.parametrize("defect", ["path-traversal", "foreign-url", "file-hash", "duplicate-day", "unsorted-days", "count", "schema"])
def test_command_rejects_invalid_archive_references_before_changing_any_public_objects(tmp_path, monkeypatch, defect):
    from collector.publish import main

    archive(tmp_path, "2026-10-21")
    archive(tmp_path)
    index_path = tmp_path / "index.json"
    index = json.loads(index_path.read_text())
    if defect == "path-traversal":
        index["days"][0]["file"] = "../../enterprise-agent/record.json"
    elif defect == "foreign-url":
        index["days"][0]["file"] = "https://other.invalid/record.json"
    elif defect == "file-hash":
        index["days"][0]["file"] = DAY + "/" + "0" * 64 + ".json"
    elif defect == "duplicate-day":
        index["days"].append(index["days"][0])
    elif defect == "unsorted-days":
        index["days"].reverse()
    elif defect == "count":
        index["days"][0]["count"] = 5
    else:
        index["schemaVersion"] = 9
    index_path.write_text(json.dumps(index) + "\n")
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 1
        assert state["objects"] == {}


@pytest.mark.parametrize("failure", ["fail_upload", "corrupt_public", "existing_bytes"])
def test_day_failure_keeps_the_previous_public_index_and_local_translation_backup(tmp_path, monkeypatch, capsys, failure):
    from collector.publish import main

    archive(tmp_path, "2026-10-21")
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert main(["--date", "2026-10-21", "--data-dir", str(tmp_path)]) == 0
        with urlopen(origin + "/" + PREFIX + "/index.json") as response:
            previous = response.read()
        entry, content = archive(tmp_path)
        key = PREFIX + "/" + entry["file"]
        if failure == "existing_bytes":
            state["objects"][key] = b"conflicting immutable object"
        else:
            state[failure] = key
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 1
        with urlopen(origin + "/" + PREFIX + "/index.json") as response:
            assert response.read() == previous
        assert (tmp_path / f"{DAY}.json").read_bytes() == content
        output = capsys.readouterr()
        assert "fixture-not-a-secret" not in output.out + output.err
        assert "private" not in output.err


def test_check_command_validates_json_without_cloud_configuration_or_network(tmp_path, monkeypatch):
    from collector.publish import main

    archive(tmp_path)
    monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)
    assert main(["--date", DAY, "--data-dir", str(tmp_path), "--check"]) == 0


@pytest.mark.parametrize("field", [
    ("id",), ("title",), ("abstract",), ("authors",), ("affiliations",), ("categories",),
    ("primaryCategory",), ("publishedAt",), ("updatedAt",), ("announceType",),
    ("absUrl",), ("pdfUrl",), ("htmlUrl",), ("translation", "status"),
    ("translation", "title"), ("translation", "abstract"), ("translation", "brief"),
])
def test_commands_reject_incomplete_paper_without_changing_the_archive(tmp_path, monkeypatch, field):
    from collector import main as collect
    from collector.publish import main
    from datetime import datetime

    paper = {
        "id": "2610.00001v2", "title": "Example Agent paper", "abstract": "Original abstract.",
        "authors": ["Example Author"], "affiliations": [], "categories": ["cs.AI"], "primaryCategory": "cs.AI",
        "publishedAt": "2026-10-22T00:00:00-04:00", "updatedAt": None, "announceType": "replace",
        "absUrl": "https://arxiv.org/abs/2610.00001v2", "pdfUrl": "https://arxiv.org/pdf/2610.00001v2",
        "htmlUrl": "https://arxiv.org/html/2610.00001v2",
        "translation": {"status": "fallback", "title": "Example Agent paper", "abstract": "Original abstract.", "brief": ""},
    }
    parent = paper if len(field) == 1 else paper[field[0]]
    del parent[field[-1]]
    # Build a matching index so failure must come from the document contract, not its hash.
    _, content = archive(tmp_path, papers=[paper])
    previous_index = (tmp_path / "index.json").read_bytes()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OSS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("OSS_ACCESS_KEY_SECRET", raising=False)
    assert main(["--date", DAY, "--data-dir", str(tmp_path), "--check"]) == 1
    assert collect(["--date", DAY, "--output-dir", str(tmp_path)], now=datetime.fromisoformat("2026-10-23T13:30:00+08:00")) == 1
    assert (tmp_path / f"{DAY}.json").read_bytes() == content
    assert (tmp_path / "index.json").read_bytes() == previous_index


def test_command_does_not_publish_a_daily_file_whose_translation_statistics_disagree(tmp_path, monkeypatch):
    from collector.publish import main

    archive(tmp_path)
    path = tmp_path / f"{DAY}.json"
    daily = json.loads(path.read_text())
    daily["stats"]["fallback"] = 1
    content = (json.dumps(daily) + "\n").encode()
    path.write_bytes(content)
    index_path = tmp_path / "index.json"
    index = json.loads(index_path.read_text())
    digest = hashlib.sha256(content).hexdigest()
    index["days"][0].update(sha256=digest, file=f"{DAY}/{digest}.json")
    index_path.write_text(json.dumps(index) + "\n")
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert main(["--date", DAY, "--data-dir", str(tmp_path)]) == 1
        assert state["objects"] == {}


@pytest.mark.parametrize("defect", [
    "unknown-tag", "duplicate-tag", "unordered-tags", "missing-state", "missing-tags", "missing-field",
    "unknown-state", "invalid-model", "invalid-version", "invalid-digest", "invalid-threshold",
    "missing-score", "extra-score", "boolean-score", "nonfinite-score", "out-of-range-score", "fallback-scores",
    "wrong-rule-tags", "wrong-score-tags", "fallback-semantic-tag",
])
def test_publisher_rejects_malformed_tagging_and_collector_only_repairs_stale_labels(tmp_path, monkeypatch, defect):
    from collector import main as collect
    from collector.publish import main as publish
    from datetime import datetime

    paper = {
        "id": "2610.00001v1", "title": "LLM Agent paper", "abstract": "Original abstract.",
        "authors": ["Example Author"], "affiliations": [], "categories": ["cs.AI"], "primaryCategory": "cs.AI",
        "publishedAt": "2026-10-22T00:00:00-04:00", "updatedAt": None, "announceType": "new",
        "absUrl": "https://arxiv.org/abs/2610.00001v1", "pdfUrl": "https://arxiv.org/pdf/2610.00001v1",
        "htmlUrl": "https://arxiv.org/html/2610.00001v1",
        "translation": {"status": "fallback", "title": "LLM Agent paper", "abstract": "Original abstract.", "brief": ""},
        "tags": ["LLM", "Agent"],
        "tagging": {
            "status": "tagged", "model": "jev-1.13.0", "rulesVersion": "daily-tags-v1", "threshold": 0.7,
            "inputSha256": "a" * 64,
            "scores": {"AI4S": 0, "CodingAgent": 0, "AgentOps": 0, "AgentHarness": 0, "企业Agent": 0},
        },
    }
    tagging = paper["tagging"]
    if defect == "unknown-tag": paper["tags"].append("invented")
    elif defect == "duplicate-tag": paper["tags"].append("LLM")
    elif defect == "unordered-tags": paper["tags"].reverse()
    elif defect == "missing-state": del paper["tagging"]
    elif defect == "missing-tags": del paper["tags"]
    elif defect == "missing-field": del tagging["model"]
    elif defect == "unknown-state": tagging["status"] = "maybe"
    elif defect == "invalid-model": tagging["model"] = ""
    elif defect == "invalid-version": tagging["rulesVersion"] = ""
    elif defect == "invalid-digest": tagging["inputSha256"] = "invalid"
    elif defect == "invalid-threshold": tagging["threshold"] = True
    elif defect == "missing-score": del tagging["scores"]["AgentOps"]
    elif defect == "extra-score": tagging["scores"]["unknown"] = 0
    elif defect == "boolean-score": tagging["scores"]["AgentOps"] = True
    elif defect == "nonfinite-score": tagging["scores"]["AgentOps"] = float("nan")
    elif defect == "out-of-range-score": tagging["scores"]["AgentOps"] = 1.1
    elif defect == "wrong-rule-tags": paper["tags"] = ["LLM"]
    elif defect == "wrong-score-tags": paper["tags"].append("CodingAgent")
    elif defect == "fallback-semantic-tag":
        tagging.update(status="fallback", scores={})
        paper["tags"].append("CodingAgent")
    else: tagging["status"] = "fallback"
    _, content = archive(tmp_path, papers=[paper])
    original_index = (tmp_path / "index.json").read_bytes()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    with object_service() as (origin, state):
        configure(monkeypatch, origin)
        assert publish(["--date", DAY, "--data-dir", str(tmp_path)]) == 1
        assert state["objects"] == {}
    if defect in {"wrong-rule-tags", "wrong-score-tags", "fallback-semantic-tag"}:
        # Public data must be self-consistent, but a collector replay can repair
        # stale derived labels after original metadata/configuration changes.
        assert (tmp_path / f"{DAY}.json").read_bytes() == content
        assert (tmp_path / "index.json").read_bytes() == original_index
        assert collect(["--date", DAY, "--output-dir", str(tmp_path)], now=datetime.fromisoformat("2026-10-23T13:30:00+08:00")) == 0
        assert publish(["--date", DAY, "--data-dir", str(tmp_path), "--check"]) == 0
        return
    assert collect(["--date", DAY, "--output-dir", str(tmp_path)], now=datetime.fromisoformat("2026-10-23T13:30:00+08:00")) == 1
    assert (tmp_path / f"{DAY}.json").read_bytes() == content
    assert (tmp_path / "index.json").read_bytes() == original_index
