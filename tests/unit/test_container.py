from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest

from mockpod.config import MockpodConfig
from mockpod.container import _base_podman_args, build_image, cache_volume_name


class TestBasePodmanArgs:
    def test_basic_args(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path)

        assert "podman" in args
        assert "run" in args
        assert "--rm" in args
        assert "--privileged" in args

    def test_krun_no_userns_keep_id(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path)
        assert "--userns=keep-id" not in args

    def test_unsafe_has_userns_keep_id(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path, unsafe=True)
        assert "--userns=keep-id" in args

    def test_krun_runtime_default(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path)
        assert "--runtime" in args
        idx = args.index("--runtime")
        assert args[idx + 1] == "krun"

    def test_unsafe_disables_krun(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path, unsafe=True)
        assert "--runtime" not in args
        assert "--privileged" in args

    def test_bind_mounts(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path)
        args_str = " ".join(args)

        assert f"{tmp_path}:/src:ro" in args_str
        assert "/results:rw" in args_str
        expected_cache = f"{cache_volume_name(config, tmp_path)}:/var/lib/mock"
        assert expected_cache in args_str

    def test_extra_volumes_ro_requires_host_mounts(self, tmp_path: Path) -> None:
        config = MockpodConfig(extra_volumes=["/data:/data:ro"])
        with pytest.raises(click.ClickException):
            _base_podman_args(config, tmp_path)

    def test_extra_volumes_ro_with_host_mounts(self, tmp_path: Path) -> None:
        config = MockpodConfig(extra_volumes=["/data:/data:ro"])
        args = _base_podman_args(config, tmp_path, host_mounts=True)
        assert "/data:/data:ro" in " ".join(args)

    def test_extra_volumes_rw_rejected_without_host_mounts(self, tmp_path: Path) -> None:
        config = MockpodConfig(extra_volumes=["/data:/data:rw,Z"])
        with pytest.raises(click.ClickException):
            _base_podman_args(config, tmp_path)

    def test_extra_volumes_no_mode_rejected_without_host_mounts(self, tmp_path: Path) -> None:
        config = MockpodConfig(extra_volumes=["/data:/data"])
        with pytest.raises(click.ClickException):
            _base_podman_args(config, tmp_path)

    def test_interactive(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path, interactive=True)
        assert "-ti" in args

    def test_host_mock_config_with_existing_dir(self, tmp_path: Path) -> None:
        mock_dir = tmp_path / "etc-mock"
        mock_dir.mkdir()
        user_conf = tmp_path / "mock.conf"
        user_conf.write_text("")

        config = MockpodConfig(
            host_mock_config={
                "mock_config_dir": str(mock_dir),
                "user_mock_config": str(user_conf),
            },
        )
        args = _base_podman_args(config, tmp_path, host_mock_config=True)
        assert f"{mock_dir}:/etc/mock:ro" in " ".join(args)

    def test_host_volumes(self, tmp_path: Path) -> None:
        config = MockpodConfig(host_volumes=["/host/keys:/keys"])
        args = _base_podman_args(config, tmp_path, host_mounts=True)
        assert "/host/keys:/keys" in " ".join(args)

    def test_host_volumes_with_options(self, tmp_path: Path) -> None:
        config = MockpodConfig(host_volumes=["/host/data:/data:rw,Z"])
        args = _base_podman_args(config, tmp_path, host_mounts=True)
        assert "/host/data:/data:rw,Z" in " ".join(args)

    def test_artifacts_dir_mounted(self, tmp_path: Path) -> None:
        config = MockpodConfig()
        args = _base_podman_args(config, tmp_path)
        artifacts_dir = config.resolved_artifacts_dir(tmp_path)
        assert f"{artifacts_dir}:/results:rw" in " ".join(args)


class TestBuildImage:
    @patch("mockpod.container._require_podman")
    @patch("mockpod.container._image_exists", return_value=True)
    @patch("subprocess.run")
    def test_skips_if_exists(
        self, mock_run: MagicMock, mock_exists: MagicMock, _mock_req: MagicMock
    ) -> None:
        config = MockpodConfig()
        build_image(config, force=False)
        mock_run.assert_not_called()

    @patch("mockpod.container._require_podman")
    @patch("mockpod.container._image_exists", return_value=False)
    @patch("subprocess.run")
    def test_builds_if_missing(
        self, mock_run: MagicMock, mock_exists: MagicMock, _mock_req: MagicMock
    ) -> None:
        config = MockpodConfig()
        build_image(config, force=False)
        mock_run.assert_called_once()

    @patch("mockpod.container._require_podman")
    @patch("mockpod.container._image_exists", return_value=True)
    @patch("subprocess.run")
    def test_force_rebuild(
        self, mock_run: MagicMock, mock_exists: MagicMock, _mock_req: MagicMock
    ) -> None:
        config = MockpodConfig()
        build_image(config, force=True)
        mock_run.assert_called_once()
