from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import click

from mockpod.builder import run_build
from mockpod.config import MockpodConfig, generate_config, load_config
from mockpod.constants import (
    CHROOT_RE,
    DEFAULT_IMAGE,
    GLOBAL_CONFIG_PATH,
    LOCAL_CONFIG_PATH,
    MOCKPOD_DIR,
)
from mockpod.container import (
    build_image,
    cache_volume_name,
    ensure_image,
    podman_run,
)
from mockpod.repo import (
    clean_artifacts,
    generate_repo_file,
    list_packages,
    print_log_paths,
)
from mockpod.serve import start_server
from mockpod.shell import cmd, heredoc

logger = logging.getLogger(__name__)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@dataclass
class Context:
    config: MockpodConfig
    project_root: Path
    host_mock_config: bool
    host_mounts: bool
    unsafe: bool


pass_ctx = click.make_pass_decorator(Context)
chroot_option = click.option(
    "-r", "--chroot", default=None, required=False, help="The mock chroot to use."
)


def _validate_chroot(chroot: str) -> str:
    if not CHROOT_RE.match(chroot):
        raise click.ClickException(
            f"Invalid chroot name: {chroot!r}. "
            "Must match [a-zA-Z0-9._-]+ (e.g. 'fedora-rawhide-x86_64')"
        )
    return chroot


@click.group()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a mockpod.toml config file. Overrides global and local configs.",
)
@click.option(
    "--project-root",
    type=click.Path(path_type=Path, exists=True),
    default=Path.cwd(),
    help="The project root directory.",
)
@click.option(
    "--resultdir",
    type=click.Path(path_type=Path),
    default=(Path.cwd() / MOCKPOD_DIR),
    help="The .mockpod output directory (absolute or relative to --project-root).",
)
@click.option(
    "--image",
    default=DEFAULT_IMAGE,
    help="The base container image for builds.",
)
@click.option(
    "--containerfile",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help=(
        "Path to a custom Containerfile for the builder image. "
        "Must include a 'builder' user in the mock group matching host UID."
    ),
)
@click.option(
    "--host-mock-config",
    is_flag=True,
    default=False,
    help="Bind-mount host mock configuration into the container (read-only).",
)
@click.option(
    "--host-mounts",
    is_flag=True,
    default=False,
    help=(
        "Enable host volume mounts from config (host_volumes). "
        "WARNING: grants the container access to those host paths."
    ),
)
@click.option(
    "--unsafe",
    is_flag=True,
    default=False,
    help=(
        "Disable the krun VM isolation (libkrun microVM). "
        "Runs with --privileged directly on the host container runtime. "
        "DANGEROUS: the container has effectively root access to the host. "
        "Only use for trusted code when krun is unavailable or you need speed."
    ),
)
@click.option(
    "--log-level",
    type=click.Choice(LOG_LEVELS, case_sensitive=False),
    default="WARNING",
    help="Set logging verbosity.",
)
@click.version_option(package_name="mockpod")
@click.pass_context
def cli(
    ctx: click.Context,
    config: Optional[Path],
    project_root: Path,
    resultdir: Path,
    image: str,
    containerfile: Optional[Path],
    host_mock_config: bool,
    host_mounts: bool,
    unsafe: bool,
    log_level: str,
) -> None:
    """
    Build RPM packages in isolated Podman containers using mock.

    Manages a local artifact repository with dependency resolution,
    build caching, and versioned history. Built RPMs can be served
    as a DNF repository over HTTP.

    Configuration is loaded from ~/.config/mockpod.toml (global),
    ./mockpod.toml (project-local), and CLI flags (highest priority).
    """
    logging.basicConfig(level=getattr(logging, log_level.upper()), format="%(message)s")

    overrides: dict[str, object] = {}
    for name, value in [
        ("resultdir", resultdir),
        ("image", image),
        ("containerfile", containerfile),
    ]:
        if value and ctx.get_parameter_source(name) == click.core.ParameterSource.COMMANDLINE:
            overrides[name] = value

    config = load_config(config_override=config, cli_overrides=overrides)
    ctx.ensure_object(dict)
    obj = Context(
        config=config,
        project_root=project_root,
        host_mock_config=host_mock_config,
        host_mounts=host_mounts,
        unsafe=unsafe,
    )

    if unsafe:
        click.echo(
            "WARNING: --unsafe disables krun VM isolation.\n"
            "The container will run with --privileged, giving it full root\n"
            "access to the host. A malicious spec file or build script can\n"
            "compromise your entire system. Do NOT use this with untrusted code.",
            err=True,
        )
        if not click.confirm("Continue without VM isolation?", default=False, err=True):
            sys.exit(1)

    if host_mounts:
        if not config.host_volumes and not config.extra_volumes:
            raise click.ClickException(
                "--host-mounts requires host_volumes or extra_volumes "
                "to be configured in mockpod.toml"
            )

        all_volumes = config.host_volumes + config.extra_volumes
        lines = ["WARNING: --host-mounts enables bind mounts to host paths:"]
        for v in all_volumes:
            lines.append(f"  {v}")

        lines.append(
            "The container has full internet access and can send data "
            "from mounted paths to the network."
        )
        warning = "\n".join(lines)

        if config.auto_confirm_host_mounts:
            logger.warning(warning)
        else:
            click.echo(warning, err=True)
            if not click.confirm("Continue?", default=False, err=True):
                sys.exit(1)

    ctx.obj = obj


@cli.command()
@click.argument(
    "package",
    type=click.Path(exists=True, path_type=Path),
    required=True,
)
@chroot_option
@click.option("--srpm-only", is_flag=True, help="Only produce the SRPM, skip binary rebuild.")
@click.option(
    "--no-cache", is_flag=True, help="Ignore rebuild detection cache, force full rebuild."
)
@click.option("--clean", is_flag=True, help="Scrub the mock chroot before building.")
@click.option(
    "--shell",
    is_flag=True,
    help="Drop into an interactive container shell after the build finishes.",
)
@click.argument("mock_args", nargs=-1, type=click.UNPROCESSED)
@pass_ctx
def build(
    ctx: Context,
    package: Path,
    chroot: Optional[str],
    srpm_only: bool,
    no_cache: bool,
    clean: bool,
    shell: bool,
    mock_args: tuple[str, ...],
) -> None:
    """
    Build an RPM package from a .spec file or .src.rpm inside a Podman container.

    Extra arguments after -- are passed directly to mock.

    \b
    Examples:
      mockpod build package/package.spec
      mockpod build package/package.src.rpm
      mockpod build package/package.src.rpm -r fedora-43-x86_64
      mockpod build package/package.src.rpm -r fedora-43-x86_64 --sources .
      mockpod build package/package.src.rpm --srpm-only
      mockpod build package/package.src.rpm --shell --clean
      mockpod build package/package.src.rpm -- --enable-network --with tests
    """
    chroot = _validate_chroot(chroot or ctx.config.mock_chroot)

    sys.exit(
        run_build(
            ctx=ctx,
            package_path=package,
            chroot=chroot,
            srpm_only=srpm_only,
            no_cache=no_cache,
            clean_chroot=clean,
            drop_shell=shell,
            extra_mock_args=list(mock_args),
        ),
    )


@cli.command()
@chroot_option
@pass_ctx
def shell(ctx: Context, chroot: Optional[str]) -> None:
    """
    Open an interactive shell in the builder container.

    Useful for manual debugging, inspecting the mock chroot, or running
    arbitrary commands in the same environment used for builds.
    """
    chroot = _validate_chroot(chroot or ctx.config.mock_chroot)
    ensure_image(ctx.config)
    sys.exit(
        podman_run(
            ctx.config,
            ctx.project_root,
            ["/bin/bash"],
            interactive=True,
            host_mock_config=ctx.host_mock_config,
            host_mounts=ctx.host_mounts,
            unsafe=ctx.unsafe,
        )
    )


@cli.command()
@chroot_option
@pass_ctx
def sandbox(ctx: Context, chroot: Optional[str]) -> None:
    """
    Open an interactive shell with the local artifact repository pre-configured.

    Launches the builder container with a DNF repository pointing at
    the built artifacts via `file://`. You can then install packages
    directly with `dnf install <package>` to test them safely inside
    the container without affecting the host system.
    """
    chroot = _validate_chroot(chroot or ctx.config.mock_chroot)
    ensure_image(ctx.config)
    repo_content = generate_repo_file(
        f"file:///results/{chroot}",
        repo_id="mockpod-local",
        name="mockpod local build artifacts",
        priority=1,
    )

    setup_cmd = (
        heredoc("/etc/yum.repos.d/mockpod-local.repo", repo_content, "REPO_EOF")
        + "\nexec /bin/bash"
    )

    sys.exit(
        podman_run(
            ctx.config,
            ctx.project_root,
            [setup_cmd],
            interactive=True,
            host_mock_config=ctx.host_mock_config,
            host_mounts=ctx.host_mounts,
            unsafe=ctx.unsafe,
        )
    )


@cli.command("list")
@chroot_option
@click.option("--history", is_flag=True, help="Show all historical builds, not just the latest.")
@click.option("--json", is_flag=True, help="Output as JSON for scripting.")
@pass_ctx
def list_cmd(ctx: Context, chroot: Optional[str], history: bool, json: bool) -> None:
    """
    List packages in the artifact repository.
    """
    artifacts_dir = ctx.config.resolved_artifacts_dir(ctx.project_root)
    list_packages(artifacts_dir, chroot=chroot, show_history=history, as_json=json)


@cli.command()
@click.argument("package")
@chroot_option
@click.option(
    "--show-nth",
    default=1,
    type=int,
    help="Show the Nth most recent build (1 = latest, 2 = previous, etc.).",
)
@pass_ctx
def logs(ctx: Context, package: str, chroot: Optional[str], show_nth: int) -> None:
    """
    Show paths to build log files for a package.
    """
    chroot = _validate_chroot(chroot or ctx.config.mock_chroot)
    artifacts_dir = ctx.config.resolved_artifacts_dir(ctx.project_root)
    print_log_paths(artifacts_dir, package, chroot, show_nth)


@cli.command()
@chroot_option
@click.option("--port", default=8080, type=int, help="TCP port to listen on.")
@click.option("--bind", default="127.0.0.1", help="Address to bind to.")
@pass_ctx
def serve(ctx: Context, chroot: Optional[str], port: int, bind: str) -> None:
    """
    Serve the artifact repository over HTTP as a DNF repo.

    Starts a local HTTP server so you can add the repository with
    'mockpod repo-file' and install built packages via dnf.

    If CHROOT is given, only that chroot directory is served.
    Otherwise, the entire artifact tree is served and available
    chroots are listed.
    """
    artifacts_dir = ctx.config.resolved_artifacts_dir(ctx.project_root)

    if chroot:
        chroot = _validate_chroot(chroot)

    ensure_image(ctx.config)
    if chroot:
        chroot_dir = artifacts_dir / chroot
        if chroot_dir.exists():
            podman_run(
                ctx.config,
                ctx.project_root,
                [cmd("createrepo_c", f"/results/{chroot}")],
                host_mock_config=False,
                host_mounts=False,
                unsafe=ctx.unsafe,
            )
    else:
        for d in artifacts_dir.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                podman_run(
                    ctx.config,
                    ctx.project_root,
                    [cmd("createrepo_c", f"/results/{d.name}")],
                    host_mock_config=False,
                    host_mounts=False,
                    unsafe=ctx.unsafe,
                )

    _loopback = {"127.0.0.1", "::1", "localhost"}
    if bind not in _loopback:
        click.echo(
            f"WARNING: Binding to {bind} exposes the artifact repository "
            "to the network without authentication.",
            err=True,
        )
        if not click.confirm("Continue?", default=False, err=True):
            sys.exit(1)

    start_server(artifacts_dir, chroot=chroot, port=port, bind=bind)


@cli.command()
@click.option("--all", "clean_all", is_flag=True, help="Remove all artifacts, cache, and image.")
@click.option("--cache", "clean_cache", is_flag=True, help="Remove the mock chroot cache volume.")
@click.option("--image", "clean_image", is_flag=True, help="Remove the mockpod builder image.")
@click.option(
    "--older-than",
    type=int,
    default=None,
    help="Remove builds older than N days.",
)
@click.option(
    "--keep-n",
    type=int,
    default=None,
    help="Keep only the last N builds per package (remove older ones).",
)
@pass_ctx
def clean(
    ctx: Context,
    clean_all: bool,
    clean_cache: bool,
    clean_image: bool,
    older_than: Optional[int],
    keep_n: Optional[int],
) -> None:
    """
    Clean up build artifacts, mock cache, or the builder image.

    Without flags, does nothing. Combine flags to clean specific things.
    """
    base_dir = ctx.config.resolved_resultdir(ctx.project_root)
    artifacts_dir = ctx.config.resolved_artifacts_dir(ctx.project_root)
    clean_artifacts(
        base_dir=base_dir,
        artifacts_dir=artifacts_dir,
        cache_volume=cache_volume_name(ctx.config, ctx.project_root),
        clean_all=clean_all,
        clean_cache=clean_cache,
        clean_image=clean_image,
        older_than_days=older_than,
        keep_n=keep_n,
    )


@cli.command("repo-file")
@click.argument("chroot")
@click.option(
    "--baseurl",
    default=None,
    help="Override the repository base URL. Default: `file://` path to artifacts.",
)
@click.option(
    "--repo-id",
    default=os.path.basename(os.getcwd()),
    help="Repository ID used in the .repo file.",
)
@click.option("--name", default=None, help="Human-readable repository name.")
@click.option(
    "--priority",
    type=int,
    default=None,
    help="DNF repository priority. Lower number = higher priority (e.g. 1 = highest).",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path. Default: stdout. Use a path to write to a file.",
)
@pass_ctx
def repo_file(
    ctx: Context,
    chroot: str,
    baseurl: Optional[str],
    repo_id: str,
    name: Optional[str],
    priority: Optional[int],
    output: Optional[Path],
) -> None:
    """
    Generate a DNF .repo file for the artifact repository.

    Creates a yum/dnf repository configuration file pointing to
    the built packages.
    """
    artifacts_dir = ctx.config.resolved_artifacts_dir(ctx.project_root)

    if baseurl is None:
        baseurl = f"file://{artifacts_dir / chroot}"

    content = generate_repo_file(
        baseurl,
        repo_id=repo_id,
        name=name or repo_id,
        priority=priority,
    )

    click.echo(
        "NOTE: Generated repo file uses gpgcheck=0 (packages are unsigned). "
        "Do not use for production systems without GPG verification.",
        err=True,
    )

    if output is None or str(output) == "-":
        click.echo(content, nl=False)
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content)
    click.echo(f"Wrote {output}")


@cli.command()
@click.option(
    "--global-config",
    is_flag=True,
    help="Create the global config at ~/.config/mockpod.toml instead of ./mockpod.toml.",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing config file and force-rebuild the builder image.",
)
@pass_ctx
def init(ctx: Context, global_config: bool, force: bool) -> None:
    """
    Initialize mockpod: generate config and build the base image.

    Creates a `mockpod.toml` configuration file (local by default)
    and builds the Podman base image used for mock builds.
    """
    target = GLOBAL_CONFIG_PATH if global_config else LOCAL_CONFIG_PATH
    if target.exists() and not force:
        click.echo(f"Config already exists: {target}")
        click.echo("Use --force to overwrite.")
        sys.exit(1)

    generate_config(target)
    click.echo(f"Created {target}")

    build_image(ctx.config, force=force)
    click.echo("Base image ready.")
