from __future__ import annotations

from pathlib import Path

from mockpod.config import MockpodConfig, generate_config, load_config
from mockpod.constants import DEFAULT_IMAGE, DEFAULT_MOCK_CHROOT, MOCKPOD_DIR


class TestMockpodConfig:
    def test_defaults(self) -> None:
        config = MockpodConfig()
        assert config.image == DEFAULT_IMAGE
        assert config.mock_chroot == DEFAULT_MOCK_CHROOT
        assert config.resultdir == MOCKPOD_DIR
        assert config.project_name is None
        assert config.history_limit == 0
        assert config.extra_volumes == []
        assert config.extra_mock_args == []

    def test_resolved_resultdir_relative(self, tmp_path: Path) -> None:
        config = MockpodConfig(resultdir="my-dir")
        assert config.resolved_resultdir(tmp_path) == tmp_path / "my-dir"

    def test_resolved_resultdir_absolute(self, tmp_path: Path) -> None:
        abs_dir = tmp_path / "opt" / "rpms"
        config = MockpodConfig(resultdir=abs_dir, project_name="myproj")
        assert config.resolved_resultdir(tmp_path) == abs_dir / "myproj"

    def test_resolved_resultdir_absolute_fallback_name(self, tmp_path: Path) -> None:
        abs_dir = tmp_path / "opt" / "rpms"
        config = MockpodConfig(resultdir=abs_dir)
        assert config.resolved_resultdir(tmp_path) == abs_dir / tmp_path.name

    def test_resolved_artifacts_dir_relative(self, tmp_path: Path) -> None:
        config = MockpodConfig(resultdir=".mockpod")
        assert config.resolved_artifacts_dir(tmp_path) == tmp_path / ".mockpod" / "artifacts"

    def test_resolved_artifacts_dir_absolute(self, tmp_path: Path) -> None:
        abs_dir = tmp_path / "var" / "lib" / "mockpod"
        config = MockpodConfig(resultdir=abs_dir, project_name="myproj")
        assert config.resolved_artifacts_dir(tmp_path) == abs_dir / "myproj" / "artifacts"

    def test_resolved_cache_dir_relative(self, tmp_path: Path) -> None:
        config = MockpodConfig(resultdir=".mockpod")
        assert config.resolved_cache_dir(tmp_path) == tmp_path / ".mockpod" / "cache"

    def test_resolved_cache_dir_absolute(self, tmp_path: Path) -> None:
        abs_dir = tmp_path / "var" / "lib" / "mockpod"
        config = MockpodConfig(resultdir=abs_dir, project_name="myproj")
        assert config.resolved_cache_dir(tmp_path) == abs_dir / "myproj" / "cache"

    def test_host_mock_config_defaults(self) -> None:
        config = MockpodConfig()
        assert config.host_mock_config.mock_config_dir == Path("/etc/mock")
        assert config.host_volumes == []


class TestLoadConfig:
    def test_load_empty(self, tmp_path: Path, monkeypatch: object) -> None:
        """Loading with no config files gives defaults."""
        import mockpod.config as config_mod

        monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.toml")  # type: ignore[attr-defined]
        monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", tmp_path / "nonexistent2.toml")  # type: ignore[attr-defined]
        config = load_config()
        assert config.image == DEFAULT_IMAGE

    def test_load_with_overrides(self, tmp_path: Path, monkeypatch: object) -> None:
        import mockpod.config as config_mod

        monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.toml")  # type: ignore[attr-defined]
        monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", tmp_path / "nonexistent2.toml")  # type: ignore[attr-defined]
        config = load_config(cli_overrides={"image": "custom:latest"})
        assert config.image == "custom:latest"

    def test_load_from_file(self, tmp_path: Path, monkeypatch: object) -> None:
        import mockpod.config as config_mod

        monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.toml")  # type: ignore[attr-defined]
        monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", tmp_path / "nonexistent2.toml")  # type: ignore[attr-defined]

        cfg_file = tmp_path / "test.toml"
        cfg_file.write_text('image = "my-image:42"\nmock_chroot = "fedora-42-x86_64"\n')

        config = load_config(config_override=cfg_file)
        assert config.image == "my-image:42"
        assert config.mock_chroot == "fedora-42-x86_64"

    def test_cli_overrides_file(self, tmp_path: Path, monkeypatch: object) -> None:
        import mockpod.config as config_mod

        monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.toml")  # type: ignore[attr-defined]
        monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", tmp_path / "nonexistent2.toml")  # type: ignore[attr-defined]

        cfg_file = tmp_path / "test.toml"
        cfg_file.write_text('image = "file-image"\n')

        config = load_config(config_override=cfg_file, cli_overrides={"image": "cli-image"})
        assert config.image == "cli-image"

    def test_layering_local_over_global(self, tmp_path: Path, monkeypatch: object) -> None:
        import mockpod.config as config_mod

        global_cfg = tmp_path / "global.toml"
        global_cfg.write_text('image = "global-image"\nmock_chroot = "fedora-42-x86_64"\n')

        local_cfg = tmp_path / "local.toml"
        local_cfg.write_text('image = "local-image"\n')

        monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_cfg)  # type: ignore[attr-defined]
        monkeypatch.setattr(config_mod, "LOCAL_CONFIG_PATH", local_cfg)  # type: ignore[attr-defined]

        config = load_config()
        assert config.image == "local-image"
        assert config.mock_chroot == "fedora-42-x86_64"


class TestGenerateConfig:
    def test_generates_file(self, tmp_path: Path) -> None:
        target = tmp_path / "mockpod.toml"
        generate_config(target)
        assert target.exists()
        content = target.read_text()
        assert "mockpod configuration" in content
        assert "image" in content
        assert "project_name" in content
