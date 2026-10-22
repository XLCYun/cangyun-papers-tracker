#!/usr/bin/env python3
"""Upload a static build, verify its bytes, and atomically activate its release."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import uuid


DEFAULT_BASE = "/var/www/cangyun-papers-tracker"
STATIC_SUFFIXES = {
    ".html", ".js", ".css", ".json", ".png", ".jpg", ".jpeg", ".webp", ".avif",
    ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".txt", ".xml", ".webmanifest",
}

# The same remote program is used with the real SSH transport and in CLI acceptance tests.
REMOTE = r'''
import hashlib, json, os, pathlib, shutil, sys

def files(root):
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("release contains a symlink")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def target(link, releases):
    if not os.path.lexists(link):
        return None
    if not link.is_symlink():
        raise ValueError("release pointer is not a symlink")
    resolved = link.resolve(strict=True)
    if resolved.parent != releases.resolve() or not resolved.is_dir():
        raise ValueError("release pointer leaves the releases directory")
    return resolved.name

def replace_link(link, release):
    temporary = link.with_name(link.name + "." + request["token"])
    temporary.symlink_to("releases/" + release)
    os.replace(temporary, link)

try:
    request = json.load(sys.stdin)
    base = pathlib.Path(request["base"])
    releases = base / "releases"
    if base.is_symlink() or releases.is_symlink():
        raise ValueError("release base must not be a symlink")
    stage = releases / (".upload-" + request["token"])
    action = request["action"]
    if action == "prepare":
        releases.mkdir(parents=True, exist_ok=True, mode=0o755)
        stage.mkdir(mode=0o755)
        result = {"stage": str(stage)}
    elif action == "activate":
        if files(stage) != request["manifest"]:
            raise ValueError("uploaded build failed SHA-256 verification")
        current = base / "current"
        previous = target(current, releases)
        target(base / "previous", releases)
        final = releases / request["release"]
        if os.path.lexists(final):
            if final.is_symlink() or files(final) != request["manifest"]:
                raise ValueError("release name already has different contents")
            shutil.rmtree(stage)
        else:
            os.replace(stage, final)
        if previous != request["release"]:
            if previous is not None:
                replace_link(base / "previous", previous)
            replace_link(current, request["release"])
        result = {"release": request["release"], "previous": target(base / "previous", releases)}
    elif action == "rollback":
        current = target(base / "current", releases)
        previous = target(base / "previous", releases)
        if current is None or previous is None:
            raise ValueError("no previous release is available")
        replace_link(base / "current", previous)
        replace_link(base / "previous", current)
        result = {"release": previous, "previous": current}
    elif action == "clean":
        if stage.exists() and not stage.is_symlink():
            shutil.rmtree(stage)
        result = {}
    else:
        raise ValueError("unknown release action")
    print(json.dumps(result))
except Exception as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
'''


def remote(host, request):
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "--", host, shlex.join(["python3", "-c", REMOTE])],
        input=json.dumps(request), text=True, capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "SSH release operation failed")
    return json.loads(result.stdout)


def build_manifest(dist):
    if dist.is_symlink() or not dist.is_dir() or not (dist / "index.html").is_file():
        raise ValueError("--dist must contain a static build with index.html")
    manifest = {}
    size = 0
    for path in sorted(dist.rglob("*")):
        relative = path.relative_to(dist)
        if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
            raise ValueError("static builds must not contain symlinks or hidden files")
        if not path.is_file():
            continue
        if path.suffix.lower() not in STATIC_SUFFIXES or "node_modules" in relative.parts:
            raise ValueError(f"not a permitted static build file: {relative}")
        data = path.read_bytes()
        manifest[relative.as_posix()] = hashlib.sha256(data).hexdigest()
        size += len(data)
    return manifest, size


def deploy(args):
    dist = Path(args.dist).absolute()
    manifest, size = build_manifest(dist)
    request = {
        "base": args.base, "release": args.release, "token": uuid.uuid4().hex,
        "manifest": manifest,
    }
    stage = remote(args.host, {**request, "action": "prepare"})["stage"]
    try:
        transfer = subprocess.run(
            ["rsync", "-a", "--delete", "--chmod=D755,F644", "--", f"{dist}/", f"{args.host}:{stage}/"],
            text=True, capture_output=True,
        )
        if transfer.returncode:
            raise RuntimeError(transfer.stderr.strip() or "static build transfer failed")
        result = remote(args.host, {**request, "action": "activate"})
    except Exception:
        try:
            remote(args.host, {**request, "action": "clean"})
        except (RuntimeError, OSError, ValueError):
            print("Incomplete upload cleanup failed; inspect the remote release state.", file=sys.stderr)
        raise
    return {**result, "files": len(manifest), "bytes": size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    deploy_parser = commands.add_parser("deploy", help="verify and activate a static release")
    deploy_parser.add_argument("--dist", default="dist")
    deploy_parser.add_argument("--release", required=True)
    rollback_parser = commands.add_parser("rollback", help="atomically restore the previous release")
    for command_parser in (deploy_parser, rollback_parser):
        command_parser.add_argument("--host", required=True, help="an existing SSH host alias")
        command_parser.add_argument("--base", default=DEFAULT_BASE)
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]*", args.host):
            raise ValueError("invalid SSH host")
        if not re.fullmatch(r"/[A-Za-z0-9_./-]+", args.base) or ".." in PurePosixPath(args.base).parts:
            raise ValueError("--base must be an absolute path without parent components or spaces")
        if len(PurePosixPath(args.base).parts) < 3:
            raise ValueError("--base must be a dedicated site directory")
        if args.command == "deploy" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.release):
            raise ValueError("invalid release name")
        if args.command == "deploy":
            result = deploy(args)
        else:
            result = remote(args.host, {"action": "rollback", "base": args.base, "token": uuid.uuid4().hex})
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
