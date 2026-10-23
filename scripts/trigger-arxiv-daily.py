#!/usr/bin/env python3
"""Trigger the existing daily workflow from ECS, without model or OSS credentials."""

import argparse
from datetime import datetime, time
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo


REPOSITORY = "XLCYun/cangyun-papers-tracker"
WORKFLOW = f"/repos/{REPOSITORY}/actions/workflows/daily.yml"
BEIJING = ZoneInfo("Asia/Shanghai")
BODY_LIMIT = 16 * 1024 * 1024
RETRY_SECONDS = 15 * 60


class TriggerError(Exception):
    """A diagnostic that never includes credentials or upstream response bodies."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def request(method, url, *, token=None, payload=None):
    headers = {"User-Agent": "cangyun-papers-ecs-trigger/1", "Accept": "application/json"}
    if token:
        headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
    else:
        headers["Cache-Control"] = "no-cache"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    try:
        # Never forward the token on redirects or through ambient proxy settings.
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(Request(url, data=data, headers=headers, method=method), timeout=20) as response:
            content = response.read(BODY_LIMIT + 1)
            if len(content) > BODY_LIMIT:
                raise TriggerError("HTTP response exceeds the size limit.")
            return response.status, content
    except HTTPError as error:
        raise TriggerError(f"{method} request failed: HTTP {error.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise TriggerError(f"{method} request failed: network unavailable or timed out.") from None


def decode(content):
    try:
        return json.loads(content)
    except (ValueError, UnicodeError):
        raise TriggerError("Service returned invalid JSON.") from None


def validate_base(value, *, github=False):
    parsed = urlsplit(value)
    loopback = parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if (
        parsed.username or parsed.password or parsed.query or parsed.fragment
        or not parsed.hostname
        or not (parsed.scheme == "https" or (loopback and parsed.scheme == "http"))
        or (github and not loopback and parsed.netloc != "api.github.com")
        or (github and parsed.path not in {"", "/"})
    ):
        raise TriggerError("Use HTTPS service URLs; the authenticated API must be api.github.com.")
    return value.rstrip("/")


def read_token(path):
    try:
        info = path.stat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise TriggerError("Credential must be a private regular file (0400 or 0600).")
        with path.open() as credential:
            token = credential.read(1025).strip()
    except OSError:
        raise TriggerError("Cannot read the GitHub credential file.") from None
    if len(token) > 1024 or not re.fullmatch(r"github_pat_[A-Za-z0-9_]+", token):
        raise TriggerError("A dedicated fine-grained GitHub Token is required.")
    return token


def published_count(base, day):
    _, content = request("GET", f"{base}/index.json")
    index = decode(content)
    if not isinstance(index, dict) or index.get("schemaVersion") != 1 or not isinstance(index.get("days"), list):
        raise TriggerError("Public daily index has an invalid schema.")
    for entry in index["days"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("date"), str):
            raise TriggerError("Public daily index contains an invalid date entry.")
        if entry["date"] != day:
            continue
        count, digest = entry.get("count"), entry.get("sha256")
        if (
            type(count) is not int or count < 0 or not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or entry.get("file") != f"{day}/{digest}.json"
        ):
            raise TriggerError("Public daily index contains an invalid archive reference.")
        _, archive = request("GET", f"{base}/{entry['file']}")
        if hashlib.sha256(archive).hexdigest() != digest:
            raise TriggerError("Published archive failed SHA-256 verification.")
        daily = decode(archive)
        if (
            not isinstance(daily, dict) or daily.get("date") != day
            or not isinstance(daily.get("papers"), list) or len(daily["papers"]) != count
        ):
            raise TriggerError("Published archive date or paper count does not match its index.")
        return count
    return None


def load_state(path, day):
    if not path.exists():
        return {"version": 1, "date": day, "attempts": 0, "complete": False}
    try:
        state = json.loads(path.read_text())
        if (
            not isinstance(state, dict) or state.get("version") != 1
            or not isinstance(state.get("date"), str)
            or type(state.get("attempts")) is not int or state["attempts"] < 0
            or type(state.get("complete")) is not bool
        ):
            raise ValueError
    except (OSError, ValueError):
        raise TriggerError("Trigger state is unreadable or invalid; refusing an untracked dispatch.") from None
    if state["date"] != day:
        return {"version": 1, "date": day, "attempts": 0, "complete": False}
    return state


def save_state(path, state):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".state-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(state, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def dispatch(api, token, inputs):
    status, body = request(
        "POST", f"{api}{WORKFLOW}/dispatches", token=token,
        payload={"ref": "main", "inputs": inputs},
    )
    if status not in {200, 204}:
        raise TriggerError(f"Unexpected dispatch response: HTTP {status}.")
    receipt = {"status": "dispatched"}
    if status == 200:
        response = decode(body)
        run_id = response.get("workflow_run_id") if isinstance(response, dict) else None
        if type(run_id) is int and run_id > 0:
            receipt["runUrl"] = f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"
    return receipt


def trigger(args, now):
    day = now.date().isoformat()
    if not time(13, 30) <= now.time().replace(tzinfo=None) < time(21):
        return {"status": "outside-window", "date": day}
    # DynamicUser exposes StateDirectory through a systemd-managed symlink.
    args.state_dir = args.state_dir.resolve()
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.state_dir.stat().st_mode & 0o077:
        raise TriggerError("Trigger state directory must be private (0700).")
    with (args.state_dir / ".lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "locked", "date": day}
        state_file = args.state_dir / "state.json"
        state = load_state(state_file, day)
        if state["complete"]:
            return {"status": "already-complete", "date": day}
        count = published_count(args.public_base_url, day)
        if count is not None:
            state["complete"] = True
            save_state(state_file, state)
            return {"status": "published", "date": day, "papers": count}
        token = read_token(args.token_file)
        _, content = request(
            "GET", f"{args.api_base_url}{WORKFLOW}/runs?branch=main&per_page=100", token=token,
        )
        payload = decode(content)
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        if not isinstance(runs, list):
            raise TriggerError("GitHub returned an invalid workflow run list.")
        for run in runs:
            if not isinstance(run, dict) or not isinstance(run.get("status"), str):
                raise TriggerError("GitHub returned an invalid workflow run.")
            if run.get("head_branch") == "main" and run["status"] != "completed":
                return {"status": "running", "date": day}
        if state["attempts"] >= args.max_dispatches:
            raise TriggerError("Daily dispatch limit reached; inspect GitHub Actions before retrying.")
        if state.get("last_attempt"):
            try:
                elapsed = now.timestamp() - datetime.fromisoformat(state["last_attempt"]).timestamp()
            except (ValueError, TypeError):
                raise TriggerError("Trigger state has an invalid attempt timestamp.") from None
            if elapsed < RETRY_SECONDS:
                return {"status": "awaiting-run", "date": day}
        # Record the attempt before POST: a timeout can mean GitHub accepted it.
        state["attempts"] += 1
        state["last_attempt"] = now.isoformat()
        save_state(state_file, state)
        return {**dispatch(args.api_base_url, token, {"date": day}), "date": day, "attempt": state["attempts"]}


def main():
    credentials = Path(os.environ.get("CREDENTIALS_DIRECTORY", "/etc/cangyun-papers-trigger"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, default=credentials / "github-token")
    parser.add_argument("--state-dir", type=Path, default=Path(os.environ.get("STATE_DIRECTORY", "/var/lib/cangyun-papers-trigger")))
    parser.add_argument("--api-base-url", default="https://api.github.com")
    parser.add_argument("--public-base-url", default="https://updates.cyunlab.com/research/arxiv-daily")
    parser.add_argument("--max-dispatches", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--now", help="Timezone-aware ISO time for deterministic operational tests.")
    parser.add_argument("--probe", action="store_true", help="Dispatch only the no-model authorization check.")
    args = parser.parse_args()
    os.umask(0o077)
    try:
        args.api_base_url = validate_base(args.api_base_url, github=True)
        args.public_base_url = validate_base(args.public_base_url)
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(BEIJING)
        if now.tzinfo is None:
            raise TriggerError("The supplied time must include a timezone.")
        now = now.astimezone(BEIJING)
        if args.probe:
            result = dispatch(args.api_base_url, read_token(args.token_file), {"verify_only": True})
        else:
            result = trigger(args, now)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (TriggerError, OSError, ValueError) as error:
        message = str(error) if isinstance(error, TriggerError) else "Local trigger configuration or state could not be read."
        print(f"Trigger failed: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
