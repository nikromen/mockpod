from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import tomllib
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticUndefined

from mockpod.constants import (
    ARTIFACTS_SUBDIR,
    CACHE_SUBDIR,
    CHROOT_RE,
    DEFAULT_IMAGE,
    DEFAULT_MOCK_CHROOT,
    DEFAULT_SETUP_COMMANDS,
    GLOBAL_CONFIG_DIR,
    GLOBAL_CONFIG_PATH,
    LOCAL_CONFIG_PATH,
    MOCKPOD_DIR,
)


class HostMockConfig(BaseModel):
    mock_config_dir: Path = Field(
        default=Path("/etc/mock"),
        description="Host directory containing mock configuration files",
    )
    user_mock_config: Path = Field(
        default=GLOBAL_CONFIG_DIR / "mock.conf",
        description="Host path to user mock config file",
    )


class MockpodConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image: str = Field(
        default=DEFAULT_IMAGE,
        description="Container image to use",
    )
    mock_chroot: str = Field(
        default=DEFAULT_MOCK_CHROOT,
        description="Default mock chroot",
    )
    resultdir: Path = Field(
        default=MOCKPOD_DIR,
        description=(
            "Base directory for all mockpod data (absolute or relative to project root).\n"
            "In local mode (relative), creates .mockpod/ in the project root.\n"
            "In global mode (absolute), creates a project-specific subdirectory."
        ),
    )
    project_name: Optional[str] = Field(
        default=None,
        description=(
            "Project name for global resultdir (used as subdirectory name).\n"
            "Defaults to the basename of the current working directory."
        ),
    )
    history_limit: int = Field(
        default=0,
        description="Maximum number of builds to keep per package (0 = unlimited)",
    )
    setup_commands: list[str] = Field(
        default_factory=lambda: list(DEFAULT_SETUP_COMMANDS),
        description=(
            "Commands to install dependencies in the builder image "
            "(each entry becomes a RUN line).\n"
            "Override for yum-based distros or custom setups."
        ),
    )
    extra_volumes: list[str] = Field(
        default_factory=list,
        description='Extra volumes to bind-mount into the container ("host:container:mode")',
    )
    extra_mock_args: list[str] = Field(
        default_factory=list,
        description="Extra arguments always passed to mock",
    )
    containerfile: Optional[Path] = Field(
        default=None,
        description=(
            "Path to a custom Containerfile for the builder image.\n"
            "When set, this replaces the default generated Containerfile.\n"
            "The image MUST have a 'builder' user in the 'mock' group matching your UID:\n"
            "  RUN useradd -u $(id -u) -m -G mock builder"
        ),
    )
    host_mock_config: HostMockConfig = Field(
        default_factory=HostMockConfig,
        description="Paths for --host-mock-config (read-only bind mounts, safe)",
    )
    host_volumes: list[str] = Field(
        default_factory=list,
        description=(
            "Host bind mounts enabled by --host-mounts (host:container or host:container:mode).\n"
            "WARNING: grants the container access to host paths.\n"
            "Use only for software you trust."
        ),
    )
    auto_confirm_host_mounts: bool = Field(
        default=False,
        description="Skip interactive confirmation for --host-mounts (log warning instead).",
    )

    @field_validator("mock_chroot")
    @classmethod
    def _validate_mock_chroot(cls, v: str) -> str:
        if not CHROOT_RE.match(v):
            raise ValueError(
                f"Invalid mock_chroot: {v!r}. "
                "Must match [a-zA-Z0-9._-]+ (e.g. 'fedora-rawhide-x86_64')"
            )
        return v

    def _resolved_base(self, project_root: Path) -> Path:
        path = self.resultdir
        if path.is_absolute():
            name = self.project_name or project_root.name
            return path / name

        return project_root / path

    def resolved_resultdir(self, project_root: Path) -> Path:
        path = self._resolved_base(project_root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolved_artifacts_dir(self, project_root: Path) -> Path:
        path = self._resolved_base(project_root) / ARTIFACTS_SUBDIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolved_cache_dir(self, project_root: Path) -> Path:
        path = self._resolved_base(project_root) / CACHE_SUBDIR
        path.mkdir(parents=True, exist_ok=True)
        return path


def _format_toml_value(value: object) -> str:
    """Format a Python value as a TOML literal."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, Path):
        return f'"{value}"'
    if isinstance(value, list):
        if not value:
            return "[]"
        items = ", ".join(_format_toml_value(v) for v in value)
        return f"[{items}]"
    return str(value)


def _resolve_default(field_info: Any) -> Any:
    """Get the effective default value from a Pydantic field."""
    if field_info.default is not PydanticUndefined:
        return field_info.default
    if field_info.default_factory is not None:
        return field_info.default_factory()
    return None


def generate_config_template() -> str:
    """Generate a commented TOML config template from MockpodConfig model fields."""
    lines = [
        "# mockpod configuration",
        "# See: https://github.com/nikromen/mockpod",
        "",
    ]

    for name, field_info in MockpodConfig.model_fields.items():
        if field_info.description:
            for desc_line in field_info.description.split("\n"):
                lines.append(f"# {desc_line}")

        default = _resolve_default(field_info)

        if isinstance(default, BaseModel):
            lines.append(f"# [{name}]")
            for sub_name, sub_field in type(default).model_fields.items():
                if sub_field.description:
                    lines.append(f"# {sub_field.description}")
                sub_default = _resolve_default(sub_field)
                if sub_default is not None:
                    lines.append(f"# {sub_name} = {_format_toml_value(sub_default)}")
                else:
                    lines.append(f"# {sub_name} =")
            lines.append("")
            continue

        if default is None:
            lines.append(f"# {name} =")
        else:
            lines.append(f"# {name} = {_format_toml_value(default)}")
        lines.append("")

    return "\n".join(lines) + "\n"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(
    config_override: Optional[Path] = None,
    cli_overrides: Optional[dict[str, Any]] = None,
) -> MockpodConfig:
    """Load config with layering: global -> local -> CLI override -> explicit file."""
    merged = {}

    merged.update(_load_toml(GLOBAL_CONFIG_PATH))
    merged.update(_load_toml(LOCAL_CONFIG_PATH))

    if config_override:
        merged.update(_load_toml(config_override))

    if cli_overrides:
        merged.update({k: v for k, v in cli_overrides.items() if v is not None})

    return MockpodConfig(**merged)


def generate_config(path: Path) -> None:
    """Write a commented config template to the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(generate_config_template())
