"""Release CLI acceptance tests; SSH and rsync are external transport boundaries."""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from threading import Thread
from urllib.request import urlopen

import pytest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "deploy-site.py"


@pytest.fixture
def release_cli(tmp_path):
    """Run the actual remote program on a local host without an SSH daemon."""
    transport = tmp_path / "transport"
    transport.mkdir()
    ssh = transport / "ssh"
    ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import subprocess, sys\n"
        "separator = sys.argv.index('--')\n"
        "command = sys.argv[separator + 2:]\n"
        "raise SystemExit(subprocess.run(command[0], shell=True).returncode)\n"
    )
    rsync = transport / "rsync"
    rsync.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, shutil, subprocess, sys\n"
        "source = pathlib.Path(sys.argv[-2])\n"
        "destination = pathlib.Path(sys.argv[-1].split(':', 1)[1])\n"
        "if os.getenv('TEST_SYSTEM_RSYNC'):\n"
        "    system_env = {**os.environ, 'PATH': os.environ['PATH'].split(os.pathsep, 1)[1]}\n"
        "    transfer = subprocess.run([os.environ['TEST_SYSTEM_RSYNC'], *sys.argv[1:-1], str(destination)], env=system_env)\n"
        "    if transfer.returncode:\n"
        "        raise SystemExit(transfer.returncode)\n"
        "else:\n"
        "    shutil.copytree(source, destination, dirs_exist_ok=True)\n"
        "if os.getenv('FAKE_RSYNC_TAMPER'):\n"
        "    (destination / 'index.html').write_text('corrupted transfer')\n"
    )
    ssh.chmod(0o755)
    rsync.chmod(0o755)
    env = {**os.environ, "PATH": f"{transport}{os.pathsep}{os.environ['PATH']}"}
    base = tmp_path / "remote" / "cangyun-papers-tracker"

    def invoke(command="deploy", *, dist=None, release="first", **extra_env):
        args = [
            sys.executable, str(CLI), command, "--host", "test-host", "--base", str(base)
        ]
        if command == "deploy":
            args += ["--dist", str(dist), "--release", release]
        return subprocess.run(args, env={**env, **extra_env}, text=True, capture_output=True)

    return invoke, base


def build(tmp_path, version):
    dist = tmp_path / version
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(f"<!doctype html><title>{version}</title>")
    (dist / "assets" / "app.js").write_text(f"console.log('{version}');\n")
    return dist


@contextmanager
def serve(current):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(current)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def get(url):
    with urlopen(url, timeout=5) as response:
        return response.read().decode()


def test_deploy_makes_verified_static_build_available_over_http(tmp_path, release_cli):
    invoke, base = release_cli
    result = invoke(dist=build(tmp_path, "first"))

    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["release"] == "first"
    assert receipt["previous"] is None
    assert receipt["files"] == 2
    with serve(base / "current") as url:
        assert get(url) == "<!doctype html><title>first</title>"
        assert get(f"{url}/assets/app.js") == "console.log('first');\n"


@pytest.mark.skipif(shutil.which("rsync") is None, reason="system rsync is not installed")
def test_deploy_with_system_rsync_serves_a_readable_static_release(tmp_path, release_cli):
    invoke, base = release_cli
    dist = build(tmp_path, "readable")
    dist.chmod(0o700)
    (dist / "index.html").chmod(0o600)
    (dist / "assets").chmod(0o700)
    (dist / "assets" / "app.js").chmod(0o700)

    result = invoke(dist=dist, TEST_SYSTEM_RSYNC=shutil.which("rsync"))

    assert result.returncode == 0, result.stderr
    with serve(base / "current") as url:
        assert get(url) == "<!doctype html><title>readable</title>"
        assert get(f"{url}/assets/app.js") == "console.log('readable');\n"
    assert stat.S_IMODE((base / "current" / "index.html").stat().st_mode) == 0o644
    assert stat.S_IMODE((base / "current").stat().st_mode) == 0o755
    assert stat.S_IMODE((base / "current" / "assets").stat().st_mode) == 0o755
    assert stat.S_IMODE((base / "current" / "assets" / "app.js").stat().st_mode) == 0o644


def test_corrupted_transfer_never_replaces_the_served_release(tmp_path, release_cli):
    invoke, base = release_cli
    assert invoke(dist=build(tmp_path, "first")).returncode == 0

    result = invoke(dist=build(tmp_path, "second"), release="second", FAKE_RSYNC_TAMPER="1")

    assert result.returncode == 1
    assert "SHA-256 verification" in result.stderr
    with serve(base / "current") as url:
        assert get(url) == "<!doctype html><title>first</title>"


def test_rollback_restores_the_previous_release_over_http(tmp_path, release_cli):
    invoke, base = release_cli
    assert invoke(dist=build(tmp_path, "first")).returncode == 0
    second = invoke(dist=build(tmp_path, "second"), release="second")
    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["previous"] == "first"

    with serve(base / "current") as url:
        assert get(url) == "<!doctype html><title>second</title>"
        result = invoke("rollback")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {"release": "first", "previous": "second"}
        assert get(url) == "<!doctype html><title>first</title>"


def test_conflicting_immutable_release_name_keeps_current_contents(tmp_path, release_cli):
    invoke, base = release_cli
    assert invoke(dist=build(tmp_path, "first")).returncode == 0

    result = invoke(dist=build(tmp_path, "different"), release="first")

    assert result.returncode == 1
    assert "different contents" in result.stderr
    with serve(base / "current") as url:
        assert get(url) == "<!doctype html><title>first</title>"


@pytest.mark.parametrize("extra_file", [".env", "paper.pdf", "main.py"])
def test_non_build_files_are_rejected_without_changing_the_site(tmp_path, release_cli, extra_file):
    invoke, base = release_cli
    assert invoke(dist=build(tmp_path, "first")).returncode == 0
    dist = build(tmp_path, "unsafe")
    (dist / extra_file).write_text("must not be published")

    result = invoke(dist=dist, release="unsafe")

    assert result.returncode == 1
    with serve(base / "current") as url:
        assert get(url) == "<!doctype html><title>first</title>"
