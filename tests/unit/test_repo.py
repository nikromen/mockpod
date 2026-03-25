from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mockpod.repo import (
    clean_artifacts,
    generate_repo_file,
    get_build_dirs,
    print_log_paths,
    update_latest_symlink_build,
)


class TestUpdateLatestSymlinkBuild:
    def test_creates_symlink(self, artifacts_dir: Path) -> None:
        chroot = "fedora-43-x86_64"
        pkg = "testpkg"
        pkg_dir = artifacts_dir / chroot / pkg
        build_dir = pkg_dir / "20260320-100000"
        build_dir.mkdir(parents=True)
        (build_dir / "testpkg-1.0-1.fc43.x86_64.rpm").write_bytes(b"fake")

        update_latest_symlink_build(pkg_dir, build_dir)
        latest = pkg_dir / "latest"

        assert latest.is_symlink()
        assert latest.resolve() == build_dir.resolve()

    def test_updates_existing_symlink(self, artifacts_dir: Path) -> None:
        chroot = "fedora-43-x86_64"
        pkg = "testpkg"
        pkg_dir = artifacts_dir / chroot / pkg

        old_build = pkg_dir / "20260320-100000"
        old_build.mkdir(parents=True)
        new_build = pkg_dir / "20260321-140000"
        new_build.mkdir(parents=True)

        update_latest_symlink_build(pkg_dir, old_build)
        update_latest_symlink_build(pkg_dir, new_build)
        latest = pkg_dir / "latest"

        assert latest.is_symlink()
        assert latest.resolve() == new_build.resolve()


class TestGetBuildDirs:
    def test_sorted_newest_first(self, populated_artifacts: Path) -> None:
        dirs = get_build_dirs(populated_artifacts, "fedora-43-x86_64", "testpkg")
        assert len(dirs) == 2
        assert dirs[0].name == "20260321-140000"
        assert dirs[1].name == "20260320-100000"

    def test_nonexistent_package(self, artifacts_dir: Path) -> None:
        dirs = get_build_dirs(artifacts_dir, "fedora-43-x86_64", "nope")
        assert dirs == []


class TestPrintLogPaths:
    def test_latest(self, populated_artifacts: Path, capsys: pytest.CaptureFixture[str]) -> None:
        print_log_paths(populated_artifacts, "testpkg", "fedora-43-x86_64", 1)
        captured = capsys.readouterr()
        assert "20260321-140000" in captured.out
        assert "latest" in captured.out
        assert "build.log" in captured.out

    def test_previous(self, populated_artifacts: Path, capsys: pytest.CaptureFixture[str]) -> None:
        print_log_paths(populated_artifacts, "testpkg", "fedora-43-x86_64", 2)
        captured = capsys.readouterr()
        assert "20260320-100000" in captured.out
        assert "#2" in captured.out

    def test_not_found(self, artifacts_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
        print_log_paths(artifacts_dir, "nope", "fedora-43-x86_64", 1)
        captured = capsys.readouterr()
        assert "No builds found" in captured.out


class TestCleanArtifacts:
    def test_keep_n(self, populated_artifacts: Path) -> None:
        clean_artifacts(
            base_dir=populated_artifacts.parent,
            artifacts_dir=populated_artifacts,
            cache_volume="mockpod-cache-test",
            keep_n=1,
        )
        dirs = get_build_dirs(populated_artifacts, "fedora-43-x86_64", "testpkg")
        assert len(dirs) == 1
        assert dirs[0].name == "20260321-140000"

        latest = populated_artifacts / "fedora-43-x86_64" / "testpkg" / "latest"
        assert latest.is_symlink()
        assert latest.resolve().name == "20260321-140000"

    @patch("mockpod.repo.subprocess.run")
    def test_clean_all(self, mock_run: MagicMock, populated_artifacts: Path) -> None:
        base_dir = populated_artifacts.parent
        clean_artifacts(
            base_dir=base_dir,
            artifacts_dir=populated_artifacts,
            cache_volume="mockpod-cache-test",
            clean_all=True,
        )
        assert not base_dir.exists()


class TestGenerateRepoFile:
    def test_minimal(self) -> None:
        content = generate_repo_file(
            "http://localhost:8080",
            repo_id="mockpod",
            name="mockpod",
        )
        assert "[mockpod]" in content
        assert "baseurl=http://localhost:8080" in content
        assert "enabled=1" in content
        assert "gpgcheck=0" in content
        assert "priority" not in content

    def test_custom_id_and_name(self) -> None:
        content = generate_repo_file(
            "file:///tmp/repo",
            repo_id="my-repo",
            name="My Local Repo",
        )
        assert "[my-repo]" in content
        assert "name=My Local Repo" in content

    def test_with_priority(self) -> None:
        content = generate_repo_file(
            "http://localhost:8080",
            repo_id="mockpod",
            name="mockpod",
            priority=10,
        )
        assert "priority=10" in content

    def test_gpgcheck_enabled(self) -> None:
        content = generate_repo_file(
            "http://localhost:8080",
            repo_id="mockpod",
            name="mockpod",
            gpgcheck=True,
        )
        assert "gpgcheck=1" in content
