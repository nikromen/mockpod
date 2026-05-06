from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

import click

from mockpod.config import MockpodConfig
from mockpod.constants import (
    CACHE_VOLUME_PREFIX,
    CONTAINERFILE_TEMPLATE,
    IMAGE_NAME,
    NETWORK_HARDENING_CMDS,
)
from mockpod.shell import cmd

logger = logging.getLogger(__name__)


def _require_podman() -> None:
    if not shutil.which("podman"):
        raise click.ClickException(
            "podman is not installed or not in PATH. Install it with: dnf install podman"
        )


def _image_exists(name: str) -> bool:
    result = subprocess.run(
        ["podman", "image", "exists", name],
        capture_output=True,
    )
    logger.debug("Image %s exists: %s", name, result.returncode == 0)
    return result.returncode == 0


def build_image(config: MockpodConfig, force: bool = False) -> None:
    _require_podman()
    if not force and _image_exists(IMAGE_NAME):
        logger.debug("Builder image %s already exists, skipping build", IMAGE_NAME)
        return

    logger.info("Building builder image %s (base: %s)...", IMAGE_NAME, config.image)

    if config.containerfile:
        if not config.containerfile.exists():
            raise click.ClickException(f"Containerfile not found: {config.containerfile}")

        subprocess.run(
            ["podman", "build", "-t", IMAGE_NAME, "-f", str(config.containerfile), "."],
            check=True,
        )
    else:
        setup_lines = "\n".join(f"RUN {cmd}" for cmd in config.setup_commands)
        containerfile = CONTAINERFILE_TEMPLATE.format(
            base_image=config.image,
            setup_commands=setup_lines,
            builder_uid=os.getuid(),
        )
        logger.debug("Building builder image from:\n%s", containerfile)
        subprocess.run(
            ["podman", "build", "-t", IMAGE_NAME, "-f", "-", "."],
            input=containerfile.encode(),
            check=True,
        )


def ensure_image(config: MockpodConfig) -> None:
    _require_podman()
    if not _image_exists(IMAGE_NAME):
        build_image(config)


def cache_volume_name(config: MockpodConfig, project_root: Path) -> str:
    """Per-project Podman volume name for mock chroot cache."""
    name = config.project_name or project_root.resolve().name
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "-", name).strip("-.")
    return f"{CACHE_VOLUME_PREFIX}-{sanitized or 'default'}"


def _base_podman_args(
    config: MockpodConfig,
    project_root: Path,
    *,
    interactive: bool = False,
    host_mock_config: bool = False,
    host_mounts: bool = False,
    unsafe: bool = False,
    cache_tag: str | None = None,
) -> list[str]:
    args = [
        "podman",
        "run",
        "--rm",
        "--privileged",
    ]

    if not unsafe:
        args.append("--network=pasta:--map-guest-addr,none")
        args.extend(["--runtime", "krun"])
    else:
        # keep-id is only safe without krun; krun's virtiofs passthrough
        # does not translate user-namespace UIDs, so root-owned overlay
        # files become inaccessible.
        args.append("--userns=keep-id")

    vol = cache_volume_name(config, project_root)
    if cache_tag:
        vol = f"{vol}-{re.sub(r'[^a-zA-Z0-9._-]', '-', cache_tag).strip('-.')}"

    args.extend(
        [
            "--security-opt",
            "label=disable",
            "-v",
            f"{project_root}:/src:ro",
            "-v",
            f"{config.resolved_artifacts_dir(project_root)}:/results:rw",
            "-v",
            f"{vol}:/var/lib/mock",
        ]
    )

    if interactive:
        args.append("-ti")

    if config.extra_volumes and not host_mounts:
        raise click.ClickException(
            "extra_volumes require --host-mounts (any host path exposed to the "
            "container is a trust decision):\n" + "\n".join(f"  {v}" for v in config.extra_volumes)
        )

    for vol in config.extra_volumes:
        args.extend(["-v", vol])

    if host_mock_config:
        mock_dir = config.host_mock_config.mock_config_dir
        if mock_dir.exists():
            args.extend(["-v", f"{mock_dir}:/etc/mock:ro"])
        else:
            raise click.ClickException(
                "Host mock configuration directory does not exist: "
                f"{config.host_mock_config.mock_config_dir}"
            )

        user_conf = config.host_mock_config.user_mock_config
        if user_conf.exists():
            args.extend(["-v", f"{user_conf}:/etc/mock/mock.conf:ro"])
        else:
            raise click.ClickException(
                "User mock configuration file does not exist: "
                f"{config.host_mock_config.user_mock_config}"
            )

    if host_mounts:
        for vol in config.host_volumes:
            args.extend(["-v", vol])

    args.extend(["-w", "/src", IMAGE_NAME])
    return args


def podman_run(
    config: MockpodConfig,
    project_root: Path,
    commands: list[str],
    *,
    interactive: bool = False,
    host_mock_config: bool = False,
    host_mounts: bool = False,
    unsafe: bool = False,
    dry_run: bool = False,
    cache_tag: str | None = None,
) -> int:
    args = _base_podman_args(
        config,
        project_root,
        interactive=interactive,
        host_mock_config=host_mock_config,
        host_mounts=host_mounts,
        unsafe=unsafe,
        cache_tag=cache_tag,
    )

    if not commands:
        if unsafe:
            args.append("/bin/bash")
        else:
            args.extend(["/bin/bash", "-c", _wrap_with_hardening("exec /bin/bash")])
    else:
        entry = "; ".join(commands)
        if unsafe:
            args.extend(["/bin/bash", "-c", f"set -e; {entry}"])
        else:
            args.extend(["/bin/bash", "-c", _wrap_with_hardening(entry)])

    if dry_run:
        click.echo(f"[dry-run]: {click.style(' '.join(args), fg='yellow', bold=True)}")
        return 0

    return _run_with_signals(args, interactive=interactive)


def _wrap_with_hardening(user_commands: str) -> str:
    """Prepend iptables hardening as root, then drop to builder user.

    Uses ``;`` instead of ``&&`` to avoid libkrun's broken ``\\u``
    unescaping which corrupts ``&`` characters.  Hardening rules are
    best-effort (krun VMs lack netfilter); the actual build command
    runs under ``set -e``.
    """
    hardening = "; ".join(f"{c} 2>/dev/null || true" for c in NETWORK_HARDENING_CMDS)
    runuser = cmd("runuser", "-u", "builder", "--", "/bin/bash", "-c", user_commands)
    return (
        f"{hardening}; chown -R builder:builder /results; set -e; "
        f"{runuser}; rc=$?; chown -R root:root /results; exit $rc"
    )


def _run_with_signals(args: list[str], *, interactive: bool = False) -> int:
    logger.debug("Running: %s", " ".join(args))

    if interactive:
        # terminal forwards signals directly
        proc = subprocess.Popen(args)
        proc.wait()
        return proc.returncode

    proc = subprocess.Popen(args, start_new_session=True)
    pgid = os.getpgid(proc.pid)

    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    sent_term = False

    def _handler(signum: int, _frame: object) -> None:
        nonlocal sent_term
        try:
            click.echo(f"Sending {signal.Signals(signum).name} to process group {pgid}")
            os.killpg(pgid, signum)
            sent_term = True
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    try:
        proc.wait()
    except KeyboardInterrupt:
        if not sent_term:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            logger.warning("Process did not exit after 15s, sending SIGKILL")
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

            proc.wait()
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)

    return proc.returncode
