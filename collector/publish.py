"""Publish archived daily JSON to its bounded OSS prefix and verify public bytes."""

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

import oss2


PREFIX = "research/arxiv-daily"
DAY_CACHE = "public, max-age=31536000, immutable"
INDEX_CACHE = "public, max-age=60, must-revalidate"


class PublishError(Exception):
    """A credential-free publication diagnostic safe for public Actions logs."""


def _public_bytes(base, key):
    request = Request(
        f"{base}/{key}?verify={uuid4().hex}",
        headers={"Cache-Control": "no-cache", "Accept-Encoding": "identity"},
    )
    with urlopen(request, timeout=30) as response:
        return response.read()


def _headers(content, cache, *, immutable=False):
    headers = {
        "Content-Type": "application/json; charset=utf-8", "Cache-Control": cache,
        "x-oss-object-acl": "public-read", "x-oss-meta-sha256": hashlib.sha256(content).hexdigest(),
    }
    if immutable:
        headers["x-oss-forbid-overwrite"] = "true"
    return headers


def _bucket():
    required = ("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET", "OSS_ENDPOINT", "OSS_BUCKET", "OSS_PUBLIC_BASE_URL")
    if any(not os.environ.get(name) for name in required):
        raise PublishError("Required OSS configuration is missing.")
    if os.environ.get("OSS_PREFIX", PREFIX).strip("/") != PREFIX:
        raise PublishError("Only the research/arxiv-daily prefix may be published.")
    for name in ("OSS_ENDPOINT", "OSS_PUBLIC_BASE_URL"):
        parsed = urlsplit(os.environ[name])
        if (not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment
                or (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}))):
            raise PublishError("OSS endpoints must be HTTPS URLs without credentials or query strings.")
    token = os.environ.get("OSS_SECURITY_TOKEN")
    auth = oss2.StsAuth(os.environ["OSS_ACCESS_KEY_ID"], os.environ["OSS_ACCESS_KEY_SECRET"], token) if token else oss2.Auth(
        os.environ["OSS_ACCESS_KEY_ID"], os.environ["OSS_ACCESS_KEY_SECRET"]
    )
    return oss2.Bucket(auth, os.environ["OSS_ENDPOINT"], os.environ["OSS_BUCKET"], connect_timeout=30)


def _verify(base, key, content):
    actual = _public_bytes(base, key)
    if len(actual) != len(content) or hashlib.sha256(actual).digest() != hashlib.sha256(content).digest():
        raise PublishError("Anonymous public verification returned different JSON bytes.")


def _publish_index(bucket, base, content):
    key = PREFIX + "/index.json"
    try:
        previous = bucket.get_object(key).read()
    except oss2.exceptions.NoSuchKey:
        previous = b'{"schemaVersion":1,"updatedAt":null,"days":[]}\n'
    try:
        bucket.put_object(key, content, headers=_headers(content, INDEX_CACHE))
        _verify(base, key, content)
    except Exception:
        try:
            bucket.put_object(key, previous, headers=_headers(previous, INDEX_CACHE))
            _verify(base, key, previous)
        except Exception:
            raise PublishError("Index publication and rollback could not be verified; retry from the Git backup.") from None
        raise PublishError("Index publication failed; the previous index was restored and publicly verified.") from None


def _archives(data_dir, requested):
    index_content = (data_dir / "index.json").read_bytes()
    index = json.loads(index_content)
    if index.get("schemaVersion") != 1 or not isinstance(index.get("days"), list):
        raise PublishError("The index does not match JSON schema version 1.")
    dates = [entry["date"] for entry in index["days"]]
    if dates != sorted(set(dates), reverse=True):
        raise PublishError("Index dates must be unique and in descending order.")
    if requested not in dates:
        raise PublishError("The requested day is missing from the local index.")
    archives = []
    for entry in index["days"]:
        day, digest = entry["date"], entry["sha256"]
        if (not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
                or date.fromisoformat(day).isoformat() != day
                or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or entry["file"] != f"{day}/{digest}.json"):
            raise PublishError("An index reference has an invalid date, hash or object path.")
        content = (data_dir / f"{day}.json").read_bytes()
        daily = json.loads(content)
        if (daily.get("schemaVersion") != 1 or daily.get("date") != day or daily.get("timezone") != "Asia/Shanghai"
                or not isinstance(daily.get("papers"), list) or type(entry["count"]) is not int
                or entry["count"] != len(daily["papers"])):
            raise PublishError("A daily JSON does not match the date, schema or paper count in its index.")
        if hashlib.sha256(content).hexdigest() != digest:
            raise PublishError("A daily JSON does not match its index hash.")
        stats = daily["stats"]
        states = [paper["translation"]["status"] for paper in daily["papers"]]
        if (any(state not in {"translated", "fallback"} for state in states)
                or any(type(stats.get(name)) is not int or stats[name] < 0 for name in ("fetched", "matched", "translated", "fallback"))
                or stats["fetched"] < len(states) or stats["matched"] != len(states)
                or stats["translated"] != states.count("translated") or stats["fallback"] != states.count("fallback")):
            raise PublishError("A daily JSON has inconsistent paper or translation statistics.")
        if not content.endswith(b"\n") or not index_content.endswith(b"\n"):
            raise PublishError("Archived JSON files must end with a newline.")
        archives.append((entry, content))
    return index_content, archives


def main(argv=None):
    """Run the publication command, keeping immutable objects before the index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data/arxiv-daily"))
    parser.add_argument("--check", action="store_true", help="Validate the local JSON backup without contacting OSS")
    args = parser.parse_args(argv)
    try:
        index_content, archives = _archives(args.data_dir, args.date.isoformat())
        if args.check:
            print(f"Validated {args.date.isoformat()} and {len(archives)} archived day(s); no remote changes.")
            return 0
        bucket = _bucket()
        base = os.environ["OSS_PUBLIC_BASE_URL"].rstrip("/")
        for entry, content in archives:
            key = PREFIX + "/" + entry["file"]
            try:
                bucket.put_object(key, content, headers=_headers(content, DAY_CACHE, immutable=True))
            except oss2.exceptions.ServerError as error:
                if error.status != 409 or error.code != "FileAlreadyExists":
                    raise
                if bucket.get_object(key).read() != content:
                    raise PublishError("An existing immutable day object has different bytes.") from None
            _verify(base, key, content)
        _publish_index(bucket, base, index_content)
    except Exception as error:
        status = getattr(error, "status", None) or getattr(error, "code", None)
        detail = str(error) if isinstance(error, PublishError) else (f"HTTP {status}" if isinstance(status, int) else type(error).__name__)
        print(f"Publisher failed: {detail}.", file=sys.stderr)
        return 1
    print(f"Published and publicly verified {args.date.isoformat()}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
