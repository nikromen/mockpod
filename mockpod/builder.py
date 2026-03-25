from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import click

from mockpod.cache import needs_rebuild, save_hash
from mockpod.container import ensure_image, podman_run
from mockpod.repo import (
    generate_repo_file,
    prune_package_builds,
    update_latest_symlink_build,
    update_repo_symlinks,
)
from mockpod.shell import assign, cmd, pipe, var, write_file

if TYPE_CHECKING:
    from mockpod.cli import Context
    from mockpod.config import MockpodConfig

logger = logging.getLogger(__name__)


def _resolve_package_name(package_path: Path) -> str:
    name = package_path.name
    if name.endswith(".spec"):
        return package_path.stem

    if name.endswith(".src.rpm"):
        nvr = name.removesuffix(".src.rpm")
        parts = nvr.rsplit("-", 2)
        if len(parts) >= 3:
            return parts[0]

        logger.warning("Bad SRPM name format: %s, using %s as package name", name, nvr)
        return nvr

    raise click.ClickException(f"Unsupported package type: {name} (expected .spec or .src.rpm)")


def _build_mock_base_args(
    config: MockpodConfig,
    chroot: str,
    *,
    clean_chroot: bool = False,
    extra_mock_args: list[str] | None = None,
) -> list[str]:
    args = ["-r", chroot]
    if clean_chroot:
        args.append("--scrub=all")

    args.extend(config.extra_mock_args)
    if extra_mock_args:
        args.extend(extra_mock_args)

    return args


def _relative_to_project(path: Path, project_root: Path) -> Path:
    resolved = path.resolve()
    project_root = project_root.resolve()
    if not resolved.is_relative_to(project_root):
        raise click.ClickException(
            f"{path} is outside the project root ({project_root}). "
            "Only files inside the project root are accessible in the container."
        )
    return resolved.relative_to(project_root)


def _build_commands_for_spec(
    package_path: Path,
    project_root: Path,
    staging_dir: str,
    repo_file: str,
    repo_content: str,
    mock_base_args: list[str],
    *,
    srpm_only: bool = False,
) -> list[str]:
    spec_rel = _relative_to_project(package_path, project_root)
    pkg_dir = spec_rel.parent
    sources_dir = f"/tmp/sources-{spec_rel.stem}"

    commands = [
        cmd("mkdir", "-p", staging_dir, sources_dir),
        write_file(repo_content, repo_file),
        # copy everything except the spec file to the sources directory
        # link it to the sources directory
        cmd(
            "find",
            str(pkg_dir),
            "-maxdepth",
            "1",
            "-type",
            "f",
            "!",
            "-name",
            "*.spec",
            "-exec",
            "ln",
            "-sf",
            "{}",
            f"{sources_dir}/",
            ";",
        ),
        # download the sources from the spec file
        cmd("spectool", "-g", "-C", sources_dir, str(spec_rel)),
        # build the SRPM
        cmd(
            "mock",
            *mock_base_args,
            "--buildsrpm",
            f"--spec={spec_rel}",
            f"--sources={sources_dir}",
            f"--resultdir={staging_dir}",
        ),
    ]

    if not srpm_only:
        # find the SRPM
        commands.append(
            assign(
                "SRPM",
                pipe(
                    cmd("find", staging_dir, "-name", "*.src.rpm"),
                    cmd("head", "-1"),
                ),
            )
        )
        # build the binary RPMs
        commands.append(
            cmd(
                "mock",
                *mock_base_args,
                "--rebuild",
                var("SRPM"),
                f"--resultdir={staging_dir}",
                f"--addrepo={repo_file}",
            )
        )

    return commands


def run_build(
    ctx: Context,
    package_path: Path,
    chroot: str,
    *,
    srpm_only: bool = False,
    no_cache: bool = False,
    clean_chroot: bool = False,
    drop_shell: bool = False,
    extra_mock_args: list[str] | None = None,
) -> int:
    package = _resolve_package_name(package_path)
    artifacts_dir = ctx.config.resolved_artifacts_dir(ctx.project_root)
    cache_dir = ctx.config.resolved_cache_dir(ctx.project_root)

    if not no_cache and not needs_rebuild(cache_dir, package, chroot, package_path):
        click.echo(f"{package}: up to date, skipping (use --no-cache to force)")
        return 0

    ensure_image(ctx.config)

    artifacts_chroot = artifacts_dir / chroot
    artifacts_chroot.mkdir(parents=True, exist_ok=True)
    update_repo_symlinks(artifacts_chroot)

    staging_name = f".{package}-staging"
    staging_dir = f"/results/{chroot}/{staging_name}"
    repo_file = f"/tmp/mockpod-local-{chroot}.repo"
    repo_content = generate_repo_file(
        f"file:///results/{chroot}",
        repo_id="local-deps",
        name="Local mockpod repo",
        priority=1,
    )
    mock_base_args = _build_mock_base_args(
        ctx.config,
        chroot,
        clean_chroot=clean_chroot,
        extra_mock_args=extra_mock_args,
    )

    createrepo_cmd = cmd("createrepo_c", f"/results/{chroot}")

    if package_path.name.endswith(".src.rpm"):
        if srpm_only:
            click.echo(f"{package}: already an SRPM, nothing to do with --srpm-only")
            return 0

        srpm_rel = _relative_to_project(package_path, ctx.project_root)
        commands = [
            createrepo_cmd,
            cmd("mkdir", "-p", staging_dir),
            write_file(repo_content, repo_file),
            cmd(
                "mock",
                *mock_base_args,
                "--rebuild",
                str(srpm_rel),
                f"--resultdir={staging_dir}",
                f"--addrepo={repo_file}",
            ),
        ]
    else:
        commands = _build_commands_for_spec(
            package_path,
            ctx.project_root,
            staging_dir,
            repo_file,
            repo_content,
            mock_base_args,
            srpm_only=srpm_only,
        )
        commands.insert(0, createrepo_cmd)

    rc = podman_run(
        ctx.config,
        ctx.project_root,
        commands,
        host_mock_config=ctx.host_mock_config,
        host_mounts=ctx.host_mounts,
        unsafe=ctx.unsafe,
    )

    if rc != 0:
        click.echo(f"Build of {package} failed (exit {rc})", err=True)
        if drop_shell:
            click.echo("Dropping into shell for debugging...")
            podman_run(
                ctx.config,
                ctx.project_root,
                [],
                interactive=True,
                host_mock_config=ctx.host_mock_config,
                host_mounts=ctx.host_mounts,
                unsafe=ctx.unsafe,
            )
        return rc

    staging = artifacts_chroot / staging_name
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    package_dir = artifacts_dir / chroot / package
    build_dir = package_dir / timestamp
    build_dir.parent.mkdir(parents=True, exist_ok=True)
    if build_dir.exists():
        if not click.confirm(
            f"Build directory {build_dir} already exists. Overwrite?",
            default=False,
        ):
            raise click.ClickException("Build directory already exists")

        click.echo(f"Overwriting build directory {build_dir}")
        shutil.rmtree(build_dir)

    staging.rename(build_dir)

    update_latest_symlink_build(package_dir, build_dir)

    if srpm_only:
        label = "SRPM"
        results = sorted(f.name for f in build_dir.iterdir() if f.name.endswith(".src.rpm"))
    else:
        label = "binary RPMs"
        results = sorted(
            f.name
            for f in build_dir.iterdir()
            if f.name.endswith(".rpm") and not f.name.endswith(".src.rpm")
        )
    if not results:
        click.echo(f"No {label} produced for {package}", err=True)
        return 1

    save_hash(cache_dir, package, chroot, package_path)

    if ctx.config.history_limit > 0:
        removed = prune_package_builds(package_dir, ctx.config.history_limit)
        if removed:
            logger.info(
                "Pruned %d old build(s) for %s (keeping %d)",
                removed,
                package,
                ctx.config.history_limit,
            )

    if not srpm_only:
        update_repo_symlinks(artifacts_chroot)
        podman_run(
            ctx.config,
            ctx.project_root,
            [cmd("createrepo_c", f"/results/{chroot}")],
            host_mock_config=ctx.host_mock_config,
            host_mounts=ctx.host_mounts,
            unsafe=ctx.unsafe,
        )

    click.echo(f"{package}: {'SRPM built' if srpm_only else 'RPMs built'} successfully")
    for name in results:
        click.echo(f"  {name}")

    if drop_shell:
        click.echo("Dropping into shell...")
        podman_run(
            ctx.config,
            ctx.project_root,
            [],
            interactive=True,
            host_mock_config=ctx.host_mock_config,
            host_mounts=ctx.host_mounts,
            unsafe=ctx.unsafe,
        )

    return 0
