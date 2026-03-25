from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project structure with a spec file."""
    pkg_dir = tmp_path / "testpkg"
    pkg_dir.mkdir()

    spec = pkg_dir / "testpkg.spec"
    spec.write_text(
        "Name: testpkg\n"
        "Version: 1.0\n"
        "Release: 1%{?dist}\n"
        "Summary: Test package\n"
        "License: MIT\n"
        "Source0: testpkg-1.0.tar.gz\n"
        "\n"
        "%description\nTest\n"
        "\n"
        "%files\n",
    )

    source = pkg_dir / "testpkg.cfg"
    source.write_text("key=value\n")

    return tmp_path


@pytest.fixture()
def artifacts_dir(tmp_path: Path) -> Path:
    """Create an empty artifacts directory."""
    d = tmp_path / "artifacts"
    d.mkdir()
    return d


@pytest.fixture()
def cache_dir(tmp_path: Path) -> Path:
    """Create an empty cache directory."""
    d = tmp_path / "cache"
    d.mkdir()
    return d


@pytest.fixture()
def populated_artifacts(artifacts_dir: Path) -> Path:
    """Create artifacts with a couple of builds."""
    chroot = artifacts_dir / "fedora-43-x86_64"
    pkg = chroot / "testpkg"

    for ts in ("20260320-100000", "20260321-140000"):
        build_dir = pkg / ts
        build_dir.mkdir(parents=True)
        (build_dir / "testpkg-1.0-1.fc43.x86_64.rpm").write_bytes(b"fake-rpm")
        (build_dir / "testpkg-1.0-1.fc43.src.rpm").write_bytes(b"fake-srpm")
        (build_dir / "build.log").write_text("build log content\n")
        (build_dir / "root.log").write_text("root log content\n")
        (build_dir / "state.log").write_text("state log content\n")

    latest = pkg / "latest"
    latest.symlink_to("20260321-140000")

    return artifacts_dir
