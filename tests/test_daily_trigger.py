"""Exercise the ECS trigger CLI across its public HTTP and credential boundaries."""

import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

import pytest


CLI = Path(__file__).resolve().parents[1] / "scripts" / "trigger-arxiv-daily.py"
DAY = "2026-10-23"
TOKEN = "github_pat_test_credential"
WORKFLOW = "/repos/XLCYun/cangyun-papers-tracker/actions/workflows/daily.yml"


@pytest.fixture
def trigger(tmp_path):
    state = {
        "index": {"schemaVersion": 1, "days": []},
        "runs": [],
        "requests": [],
        "index_status": 200,
        "runs_status": 200,
        "dispatch_status": 204,
        "archive": b"",
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body=b"", location=None):
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            state["requests"].append(("GET", self.path, self.headers.get("Authorization"), None))
            if self.path.startswith("/public/index.json"):
                self.send(state["index_status"], json.dumps(state["index"]).encode())
            elif self.path.startswith(WORKFLOW + "/runs?"):
                self.send(state["runs_status"], json.dumps({"workflow_runs": state["runs"]}).encode())
            elif self.path.startswith("/public/" + DAY + "/"):
                self.send(200, state["archive"])
            else:
                self.send(404)

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(("POST", self.path, self.headers.get("Authorization"), payload))
            self.send(
                state["dispatch_status"],
                (TOKEN + " upstream diagnostic must remain private").encode(),
                location="/leaked" if state["dispatch_status"] == 302 else None,
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "github-token"
    token_file.write_text(TOKEN)
    token_file.chmod(0o600)
    directory = tmp_path / "state"
    base = f"http://127.0.0.1:{server.server_port}"

    def invoke(*extra, now="2026-10-23T13:30:00+08:00", env=None):
        return subprocess.run(
            [
                sys.executable, str(CLI),
                "--state-dir", str(directory), "--token-file", str(token_file),
                "--api-base-url", base, "--public-base-url", base + "/public",
                "--now", now, *extra,
            ],
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
        )

    state.update(invoke=invoke, token_file=token_file, directory=directory)
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def posts(state):
    return [request for request in state["requests"] if request[0] == "POST"]


def published(state, count=0):
    state["archive"] = json.dumps({"date": DAY, "papers": [{}] * count}).encode()
    digest = hashlib.sha256(state["archive"]).hexdigest()
    state["index"]["days"] = [{
        "date": DAY, "count": count, "sha256": digest, "file": f"{DAY}/{digest}.json",
    }]


def test_dispatches_only_the_expected_main_workflow_with_dated_input(trigger):
    result = trigger["invoke"]()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "dispatched"
    assert posts(trigger) == [(
        "POST", WORKFLOW + "/dispatches", "Bearer " + TOKEN,
        {"ref": "main", "inputs": {"date": DAY}},
    )]
    public = [request for request in trigger["requests"] if request[1].startswith("/public/")]
    assert all(request[2] is None for request in public)


def test_published_zero_paper_day_counts_as_complete_and_is_cached(trigger):
    published(trigger)
    first = trigger["invoke"]()
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["status"] == "published"
    request_count = len(trigger["requests"])
    second = trigger["invoke"]()
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["status"] == "already-complete"
    assert len(trigger["requests"]) == request_count
    assert posts(trigger) == []


def test_does_not_dispatch_while_a_main_workflow_is_active(trigger):
    trigger["runs"] = [{"id": 123, "head_branch": "main", "status": "in_progress"}]
    result = trigger["invoke"]()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "running"
    assert posts(trigger) == []


@pytest.mark.parametrize("now", [
    "2026-10-23T13:29:59+08:00", "2026-10-23T21:00:00+08:00",
])
def test_outside_beijing_dispatch_window_does_not_contact_services(trigger, now):
    result = trigger["invoke"](now=now)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "outside-window"
    assert trigger["requests"] == []


@pytest.mark.parametrize("failure", ["index_status", "runs_status"])
def test_source_or_github_read_failure_does_not_become_a_dispatch(trigger, failure):
    trigger[failure] = 503
    result = trigger["invoke"]()
    assert result.returncode == 1
    assert posts(trigger) == []


def test_ambiguous_post_failure_is_counted_and_active_run_prevents_duplicate(trigger):
    trigger["dispatch_status"] = 500
    failed = trigger["invoke"]()
    assert failed.returncode == 1
    assert TOKEN not in failed.stderr + failed.stdout
    saved = json.loads((trigger["directory"] / "state.json").read_text())
    assert saved["attempts"] == 1
    trigger["runs"] = [{"id": 123, "head_branch": "main", "status": "queued"}]
    retry = trigger["invoke"](now="2026-10-23T13:45:00+08:00")
    assert retry.returncode == 0, retry.stderr
    assert json.loads(retry.stdout)["status"] == "running"
    assert len(posts(trigger)) == 1


def test_finite_daily_dispatch_limit_prevents_repeated_model_spending(trigger):
    trigger["dispatch_status"] = 500
    for minute in ("13:30", "13:45", "14:00", "14:15"):
        result = trigger["invoke"](now=f"{DAY}T{minute}:00+08:00")
        assert result.returncode == 1
    assert len(posts(trigger)) == 3
    assert "dispatch limit" in result.stderr


def test_too_soon_repeat_does_not_send_another_post(trigger):
    assert trigger["invoke"]().returncode == 0
    result = trigger["invoke"](now="2026-10-23T13:31:00+08:00")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "awaiting-run"
    assert len(posts(trigger)) == 1


def test_token_is_not_forwarded_through_a_redirect_or_printed_from_error_body(trigger):
    trigger["dispatch_status"] = 302
    result = trigger["invoke"]()
    assert result.returncode == 1
    assert TOKEN not in result.stdout + result.stderr
    assert not any(request[1] == "/leaked" for request in trigger["requests"])


@pytest.mark.parametrize("bad_token,mode", [("ghp_classic_token", 0o600), (TOKEN, 0o644)])
def test_refuses_classic_or_publicly_readable_credentials(trigger, bad_token, mode):
    trigger["token_file"].write_text(bad_token)
    trigger["token_file"].chmod(mode)
    result = trigger["invoke"]()
    assert result.returncode == 1
    assert posts(trigger) == []
    assert bad_token not in result.stdout + result.stderr


def test_publication_is_not_complete_if_archive_hash_is_wrong(trigger):
    published(trigger)
    trigger["archive"] = b"tampered"
    result = trigger["invoke"]()
    assert result.returncode == 1
    assert posts(trigger) == []
    assert "SHA-256" in result.stderr


def test_probe_only_dispatches_the_free_authorization_check(trigger):
    result = trigger["invoke"]("--probe", now="2026-10-23T09:00:00+08:00")
    assert result.returncode == 0, result.stderr
    assert posts(trigger)[0][3] == {"ref": "main", "inputs": {"verify_only": True}}
    assert len(trigger["requests"]) == 1


def test_concurrent_trigger_cannot_dispatch_twice(trigger):
    trigger["directory"].mkdir(mode=0o700)
    with (trigger["directory"] / ".lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = trigger["invoke"]()
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "locked"
    assert posts(trigger) == []


def test_utc_clock_is_resolved_to_the_beijing_daily_date(trigger):
    result = trigger["invoke"](now="2026-10-23T05:30:00+00:00")
    assert result.returncode == 0, result.stderr
    assert posts(trigger)[0][3]["inputs"] == {"date": DAY}


def test_corrupt_local_state_refuses_to_reset_dispatch_counts(trigger):
    trigger["directory"].mkdir(mode=0o700)
    (trigger["directory"] / "state.json").write_text("{broken")
    result = trigger["invoke"]()
    assert result.returncode == 1
    assert posts(trigger) == []
    assert trigger["requests"] == []


def test_authenticated_api_cannot_be_changed_to_an_external_host(trigger):
    result = trigger["invoke"]("--api-base-url", "https://example.com")
    assert result.returncode == 1
    assert trigger["requests"] == []


def test_systemd_dynamic_user_state_directory_symlink_is_supported(trigger):
    private = trigger["directory"].with_name("private-state")
    private.mkdir(mode=0o700)
    trigger["directory"].symlink_to(private, target_is_directory=True)
    result = trigger["invoke"]()
    assert result.returncode == 0, result.stderr
    assert len(posts(trigger)) == 1


def test_systemd_credential_acl_read_mask_is_supported_only_in_credential_directory(trigger):
    trigger["token_file"].chmod(0o440)
    rejected = trigger["invoke"]()
    assert rejected.returncode == 1
    assert posts(trigger) == []
    accepted = trigger["invoke"](env={
        "CREDENTIALS_DIRECTORY": str(trigger["token_file"].parent),
    })
    assert accepted.returncode == 0, accepted.stderr
    assert len(posts(trigger)) == 1
