"""Integration tests that run real mock builds.

These require mock and createrepo_c to be installed, and the user to be
in the mock group. Run with: just test-integration
"""

from __future__ import annotations

import functools
import shutil
import subprocess
import threading
import time
from collections.abc import Generator
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Optional

import pytest

from mockpod.cache import needs_rebuild, save_hash
from mockpod.repo import (
    generate_repo_file,
    update_latest_symlink_build,
    update_repo_symlinks,
)

DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_CHROOT = "fedora-rawhide-x86_64"


def _archive_staging(artifacts: Path, chroot: str, package: str) -> Path:
    """Rename staging dir to a timestamped build dir and update the latest symlink."""
    staging = artifacts / chroot / f".{package}-staging"
    pkg_dir = artifacts / chroot / package
    pkg_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    build_dir = pkg_dir / timestamp
    staging.rename(build_dir)
    update_latest_symlink_build(pkg_dir, build_dir)
    return build_dir


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _mock_buildsrpm(
    spec: Path,
    sources_dir: Path,
    resultdir: Path,
    chroot: str = DEFAULT_CHROOT,
) -> Path:
    resultdir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "mock",
            "-r",
            chroot,
            "--buildsrpm",
            "--enable-network",
            f"--spec={spec}",
            f"--sources={sources_dir}",
            f"--resultdir={resultdir}",
        ],
        check=True,
    )
    srpms = list(resultdir.glob("*.src.rpm"))
    assert srpms, f"No SRPM produced in {resultdir}"
    return srpms[0]


def _mock_rebuild(
    srpm: Path,
    resultdir: Path,
    addrepo: Optional[str] = None,
    chroot: str = DEFAULT_CHROOT,
) -> list[Path]:
    cmd = [
        "mock",
        "-r",
        chroot,
        "--rebuild",
        str(srpm),
        f"--resultdir={resultdir}",
    ]
    if addrepo:
        cmd.append(f"--addrepo={addrepo}")
    subprocess.run(cmd, check=True)
    rpms = [f for f in resultdir.glob("*.rpm") if not f.name.endswith(".src.rpm")]
    assert rpms, f"No binary RPMs produced in {resultdir}"
    return rpms


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> Generator[Path, None, None]:
    """Copy test data into a temporary workspace with artifacts/cache dirs."""
    for pkg in ("hello", "deptest", "patched"):
        shutil.copytree(DATA_DIR / pkg, tmp_path / pkg)
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "cache").mkdir()
    yield tmp_path


@pytest.fixture()
def built_hello(workspace: Path) -> Generator[Path, None, None]:
    """Build hello package and archive it into workspace/artifacts."""
    artifacts = workspace / "artifacts"
    staging = artifacts / DEFAULT_CHROOT / ".hello-staging"

    srpm = _mock_buildsrpm(
        spec=workspace / "hello" / "hello.spec",
        sources_dir=workspace / "hello",
        resultdir=staging,
    )
    _mock_rebuild(srpm, staging)
    _archive_staging(artifacts, DEFAULT_CHROOT, "hello")
    update_repo_symlinks(artifacts / DEFAULT_CHROOT)
    subprocess.run(
        ["createrepo_c", str(artifacts / DEFAULT_CHROOT)], check=True, capture_output=True
    )

    yield workspace


@pytest.fixture()
def repo_server(built_hello: Path) -> Generator[tuple[HTTPServer, str], None, None]:
    """Start an HTTP server over the built artifacts, shut it down after the test."""
    chroot_dir = built_hello / "artifacts" / DEFAULT_CHROOT
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(chroot_dir))
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)

    yield server, f"http://127.0.0.1:{port}"

    server.shutdown()


@pytest.fixture()
def installroot(
    repo_server: tuple[HTTPServer, str],
    workspace: Path,
) -> Generator[Path, None, None]:
    """Download hello RPM from the HTTP repo and install into an isolated installroot."""
    _server, repo_url = repo_server
    root = workspace / "installroot"
    root.mkdir(parents=True, exist_ok=True)

    artifacts_chroot = workspace / "artifacts" / DEFAULT_CHROOT
    rpm_name = next(
        (
            f.name
            for f in artifacts_chroot.iterdir()
            if f.name.startswith("hello-1.0") and f.name.endswith(".x86_64.rpm")
        ),
        None,
    )
    assert rpm_name, "No hello RPM found in artifacts"

    rpm_path = root / rpm_name
    subprocess.run(
        ["curl", "-sf", "-o", str(rpm_path), f"{repo_url}/{rpm_name}"],
        check=True,
    )

    subprocess.run(
        ["rpm", "--root", str(root), "-ivh", "--nodeps", str(rpm_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    yield root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHelloBuild:
    def test_build_hello(self, built_hello: Path) -> None:
        """Build the minimal hello package from scratch."""
        artifacts = built_hello / "artifacts"
        builds = list((artifacts / DEFAULT_CHROOT / "hello").iterdir())
        build_dir = next(
            d for d in builds if d.is_dir() and not d.is_symlink() and not d.name.startswith(".")
        )
        rpms = [f.name for f in build_dir.iterdir() if f.name.endswith(".rpm")]
        assert any("hello-1.0" in r and not r.endswith(".src.rpm") for r in rpms)
        assert any("hello-devel" in r for r in rpms)

        latest = artifacts / DEFAULT_CHROOT / "hello" / "latest"
        assert latest.is_symlink()


class TestDependencyResolution:
    def test_deptest_uses_hello_from_local_repo(self, built_hello: Path) -> None:
        """Build deptest which BuildRequires hello-devel from the local repo."""
        artifacts = built_hello / "artifacts"

        dep_staging = artifacts / DEFAULT_CHROOT / ".deptest-staging"
        srpm = _mock_buildsrpm(
            spec=built_hello / "deptest" / "deptest.spec",
            sources_dir=built_hello / "deptest",
            resultdir=dep_staging,
        )

        repo_url = f"file://{artifacts / DEFAULT_CHROOT}"
        _mock_rebuild(srpm, dep_staging, addrepo=repo_url)

        build_dir = _archive_staging(artifacts, DEFAULT_CHROOT, "deptest")
        rpms = [f.name for f in build_dir.iterdir() if f.name.endswith(".rpm")]
        assert any("deptest-1.0" in r and not r.endswith(".src.rpm") for r in rpms)


class TestPatchedBuild:
    def test_build_with_patch(self, workspace: Path) -> None:
        """Build a package that applies a patch from sources directory."""
        artifacts = workspace / "artifacts"
        pkg_dir = workspace / "patched"
        staging = artifacts / DEFAULT_CHROOT / ".patched-staging"

        srpm = _mock_buildsrpm(
            spec=pkg_dir / "patched.spec",
            sources_dir=pkg_dir,
            resultdir=staging,
        )
        _mock_rebuild(srpm, staging)

        build_dir = _archive_staging(artifacts, DEFAULT_CHROOT, "patched")
        rpms = [
            f.name
            for f in build_dir.iterdir()
            if f.name.endswith(".rpm") and not f.name.endswith(".src.rpm")
        ]
        assert any("patched-1.0" in r for r in rpms)


class TestRebuildDetection:
    def test_cache_skips_unchanged(self, workspace: Path) -> None:
        """After saving hash, unchanged spec is detected as up-to-date."""
        cache = workspace / "cache"
        spec = workspace / "hello" / "hello.spec"

        assert needs_rebuild(cache, "hello", DEFAULT_CHROOT, spec)

        save_hash(cache, "hello", DEFAULT_CHROOT, spec)
        assert not needs_rebuild(cache, "hello", DEFAULT_CHROOT, spec)

    def test_cache_detects_spec_change(self, workspace: Path) -> None:
        """Modifying the spec triggers a rebuild."""
        cache = workspace / "cache"
        spec = workspace / "hello" / "hello.spec"

        save_hash(cache, "hello", DEFAULT_CHROOT, spec)

        spec.write_text(spec.read_text().replace("1.0", "2.0"))
        assert needs_rebuild(cache, "hello", DEFAULT_CHROOT, spec)

    def test_cache_detects_patch_change(self, workspace: Path) -> None:
        """Modifying a patch file triggers a rebuild."""
        cache = workspace / "cache"
        spec = workspace / "patched" / "patched.spec"

        save_hash(cache, "patched", DEFAULT_CHROOT, spec)

        patch = workspace / "patched" / "fix-message.patch"
        patch.write_text(patch.read_text().replace("patched", "modified"))
        assert needs_rebuild(cache, "patched", DEFAULT_CHROOT, spec)


class TestServeAndInstall:
    def test_repo_serves_repodata(self, repo_server: tuple[HTTPServer, str]) -> None:
        """Verify the HTTP server serves valid repodata."""
        _server, repo_url = repo_server
        result = subprocess.run(
            ["curl", "-sf", f"{repo_url}/repodata/repomd.xml"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "repomd" in result.stdout

    def test_repo_file_generation(self, built_hello: Path) -> None:
        """Verify generate_repo_file produces valid .repo content."""
        content = generate_repo_file(
            "http://127.0.0.1:8080",
            repo_id="mockpod-test",
            name="mockpod-test",
            priority=1,
        )

        assert "[mockpod-test]" in content
        assert "baseurl=http://127.0.0.1:8080" in content
        assert "priority=1" in content

    def test_hello_installable(self, installroot: Path) -> None:
        """Install hello from served repo and verify it."""
        result = subprocess.run(
            ["rpm", "--root", str(installroot), "-q", "hello"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "hello-1.0" in result.stdout

    def test_hello_binary_exists(self, installroot: Path) -> None:
        """Verify the hello binary was installed."""
        assert (installroot / "usr" / "bin" / "hello").exists()


class TestSandbox:
    """Test the sandbox repo setup: file:// repo is valid and packages are visible."""

    def test_file_repo_has_repodata(self, built_hello: Path) -> None:
        """Verify the artifacts directory contains valid repodata for file:// access."""
        chroot_dir = built_hello / "artifacts" / DEFAULT_CHROOT
        repomd = chroot_dir / "repodata" / "repomd.xml"
        assert repomd.exists(), "repodata/repomd.xml missing from artifacts"
        assert "repomd" in repomd.read_text()

    def test_generate_sandbox_repo_file(self, built_hello: Path) -> None:
        """Verify generate_repo_file produces correct content for sandbox use."""
        chroot_dir = built_hello / "artifacts" / DEFAULT_CHROOT
        content = generate_repo_file(
            f"file://{chroot_dir}",
            repo_id="mockpod-local",
            name="mockpod local build artifacts",
            priority=1,
        )
        assert "[mockpod-local]" in content
        assert f"baseurl=file://{chroot_dir}" in content
        assert "priority=1" in content
        assert "gpgcheck=0" in content

    def test_dnf_sees_hello_via_file_repo(self, built_hello: Path) -> None:
        """Verify dnf can list packages from the file:// repo."""
        chroot_dir = built_hello / "artifacts" / DEFAULT_CHROOT
        result = subprocess.run(
            [
                "dnf",
                "repoquery",
                "--disablerepo=*",
                f"--repofrompath=mockpod-local,file://{chroot_dir}",
                "--enablerepo=mockpod-local",
                "--nogpgcheck",
                "hello",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout
