from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import click

from mockpod.constants import IMAGE_NAME, LATEST_SYMLINK

logger = logging.getLogger(__name__)


def update_repo_symlinks(repo_path: Path) -> None:
    """
    Recreate RPM symlinks in the repository directory.

    Symlinks latest RPMs directly into the repository directory so that
    createrepo_c metadata paths match the file:// URLs mock will use.
    Uses relative paths so links work both on host and inside the container.

    Safe for concurrent callers: stale symlinks and races are tolerated.
    """
    _clean_rpm_symlinks(repo_path)

    rpms = _collect_latest_rpms(repo_path)
    for rpm in rpms:
        link = repo_path / rpm.name
        rel_target = rpm.resolve().relative_to(repo_path.resolve())
        try:
            link.symlink_to(rel_target)
            logger.debug("Creating RPM symlink: %s -> %s", link, rel_target)
        except FileExistsError:
            logger.debug("RPM symlink already exists: %s", link)


def _clean_rpm_symlinks(repo_path: Path) -> None:
    for f in repo_path.iterdir():
        if f.is_symlink() and f.name.endswith(".rpm"):
            logger.debug("Removing old RPM symlink: %s", f)
            try:
                f.unlink()
            except FileNotFoundError:
                pass


def _collect_latest_rpms(repo_path: Path) -> list[Path]:
    rpms = []
    for pkg_dir in repo_path.iterdir():
        if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
            logger.debug("Skipping non-directory: %s", pkg_dir)
            continue

        latest = pkg_dir / LATEST_SYMLINK
        if latest.is_symlink() or latest.is_dir():
            for f in latest.iterdir():
                if f.name.endswith(".rpm") and not f.name.endswith(".src.rpm"):
                    logger.debug("Adding RPM: %s", f)
                    rpms.append(f.resolve())

    return rpms


def update_latest_symlink_build(package_dir: Path, build_dir: Path) -> None:
    """Update 'latest' symlink to point at the given build directory."""
    latest = package_dir / LATEST_SYMLINK
    if latest.is_symlink():
        latest.unlink()

    latest.symlink_to(build_dir.name)


def get_build_dirs(resultdir: Path, chroot: str, package: str) -> list[Path]:
    """Get all build directories for a package, sorted newest first."""
    pkg_dir = resultdir / chroot / package
    if not pkg_dir.exists():
        return []

    dirs = [
        d
        for d in pkg_dir.iterdir()
        if d.is_dir() and not d.is_symlink() and not d.name.startswith(".")
    ]
    dirs.sort(key=lambda d: d.name, reverse=True)
    return dirs


def print_log_paths(resultdir: Path, package: str, chroot: str, run_n: int) -> None:
    """Print the directory path and log file paths for a build."""
    builds = get_build_dirs(resultdir, chroot, package)
    if not builds:
        click.echo(f"No builds found for {package} in {chroot}")
        return

    idx = run_n - 1
    if idx >= len(builds):
        click.echo(f"Only {len(builds)} build(s) available, requested #{run_n}")
        return

    build_dir = builds[idx]
    label = "latest" if idx == 0 else f"#{run_n}"
    click.echo(f"{package} | {chroot} | {build_dir.name} ({label})")
    click.echo(f"  {build_dir}")

    for log_name in ("build.log", "root.log", "state.log"):
        log_path = build_dir / log_name
        marker = "*" if log_path.exists() else " "
        click.echo(f"  {marker} {log_path}")


def list_packages(
    resultdir: Path,
    chroot: Optional[str] = None,
    *,
    show_history: bool = False,
    as_json: bool = False,
) -> None:
    """List packages in the artifact repo."""
    if not resultdir.exists():
        click.echo("No artifacts found.")
        return

    chroots = [resultdir / chroot] if chroot else sorted(resultdir.iterdir())
    entries: list[dict[str, Any]] = []

    for chroot_dir in chroots:
        if not chroot_dir.is_dir() or chroot_dir.name.startswith("."):
            continue

        for pkg_dir in sorted(chroot_dir.iterdir()):
            if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
                continue

            builds = get_build_dirs(resultdir, chroot_dir.name, pkg_dir.name)
            if not builds:
                continue

            if show_history:
                for b in builds:
                    rpms = [f.name for f in b.iterdir() if f.name.endswith(".rpm")]
                    entries.append(
                        {
                            "chroot": chroot_dir.name,
                            "package": pkg_dir.name,
                            "build": b.name,
                            "rpms": rpms,
                        }
                    )
            else:
                latest = builds[0]
                rpms = [f.name for f in latest.iterdir() if f.name.endswith(".rpm")]
                entries.append(
                    {
                        "chroot": chroot_dir.name,
                        "package": pkg_dir.name,
                        "build": latest.name,
                        "builds": len(builds),
                        "rpms": rpms,
                    }
                )

    if as_json:
        click.echo(json.dumps(entries, indent=2))
        return

    if not entries:
        click.echo("No packages found.")
        return

    for e in entries:
        rpms_str = ", ".join(str(r) for r in e.get("rpms", []))
        builds_str = f" ({e['builds']} builds)" if "builds" in e else ""
        click.echo(f"  {e['chroot']} / {e['package']} / {e['build']}{builds_str}")
        if rpms_str:
            click.echo(f"    {rpms_str}")


def clean_artifacts(
    *,
    base_dir: Path,
    artifacts_dir: Path,
    cache_volume: str,
    clean_all: bool = False,
    clean_cache: bool = False,
    clean_image: bool = False,
    older_than_days: Optional[int] = None,
    keep_n: Optional[int] = None,
) -> None:
    """
    Clean up artifacts, cache, and/or image.

    base_dir is the top-level mockpod directory (.mockpod/ or <global>/<project>/).
    artifacts_dir is the artifacts subdirectory within base_dir.
    """
    if clean_all:
        if base_dir.exists():
            shutil.rmtree(base_dir)
            click.echo(f"Removed {base_dir}")
        _remove_cache(cache_volume)
        _remove_image()
        return

    if clean_cache:
        _remove_cache(cache_volume)

    if clean_image:
        _remove_image()

    if older_than_days is not None:
        _remove_older_than(artifacts_dir, older_than_days)

    if keep_n is not None:
        _remove_keep_n(artifacts_dir, keep_n)


def _remove_cache(volume_name: str) -> None:
    subprocess.run(["podman", "volume", "rm", "-f", volume_name], capture_output=True)
    click.echo(f"Removed mock cache volume ({volume_name}).")


def _remove_image() -> None:
    subprocess.run(["podman", "rmi", "-f", IMAGE_NAME], capture_output=True)
    click.echo("Removed base image.")


def _remove_older_than(resultdir: Path, days: int) -> None:
    cutoff = time.time() - timedelta(days=days).total_seconds()
    removed = 0
    for chroot_dir in _iter_chroot_dirs(resultdir):
        for pkg_dir in chroot_dir.iterdir():
            if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
                continue
            for build_dir in pkg_dir.iterdir():
                if build_dir.is_symlink() or not build_dir.is_dir():
                    continue
                if build_dir.stat().st_mtime < cutoff:
                    shutil.rmtree(build_dir)
                    removed += 1
            _fix_latest_symlink(pkg_dir)
    click.echo(f"Removed {removed} build(s) older than {days} days.")


def _remove_keep_n(resultdir: Path, keep: int) -> None:
    removed = 0
    for chroot_dir in _iter_chroot_dirs(resultdir):
        for pkg_dir in chroot_dir.iterdir():
            if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
                continue
            builds = sorted(
                (d for d in pkg_dir.iterdir() if d.is_dir() and not d.is_symlink()),
                key=lambda d: d.name,
                reverse=True,
            )
            for old in builds[keep:]:
                shutil.rmtree(old)
                removed += 1
            _fix_latest_symlink(pkg_dir)
    click.echo(f"Removed {removed} build(s), keeping last {keep} per package.")


def prune_package_builds(pkg_dir: Path, keep: int) -> int:
    """
    Remove old builds for a single package, keeping the last `keep` builds.

    Returns the number of builds removed.
    """
    builds = sorted(
        (d for d in pkg_dir.iterdir() if d.is_dir() and not d.is_symlink()),
        key=lambda d: d.name,
        reverse=True,
    )
    removed = 0
    for old in builds[keep:]:
        shutil.rmtree(old)
        removed += 1

    if removed:
        _fix_latest_symlink(pkg_dir)

    return removed


def _fix_latest_symlink(pkg_dir: Path) -> None:
    """Re-point 'latest' to the newest remaining build."""
    latest = pkg_dir / LATEST_SYMLINK
    if latest.is_symlink():
        latest.unlink()

    builds = sorted(
        (d for d in pkg_dir.iterdir() if d.is_dir() and not d.is_symlink()),
        key=lambda d: d.name,
        reverse=True,
    )
    if builds:
        latest.symlink_to(builds[0].name)


def _iter_chroot_dirs(resultdir: Path) -> list[Path]:
    if not resultdir.exists():
        return []
    return [d for d in resultdir.iterdir() if d.is_dir() and not d.name.startswith(".")]


def generate_repo_file(
    baseurl: str,
    *,
    repo_id: str,
    name: str,
    priority: Optional[int] = None,
    gpgcheck: bool = False,
) -> str:
    """Generate the contents of a DNF .repo file."""
    lines = [
        f"[{repo_id}]",
        f"name={name}",
        f"baseurl={baseurl}",
        "enabled=1",
        f"gpgcheck={'1' if gpgcheck else '0'}",
    ]
    if priority is not None:
        lines.append(f"priority={priority}")
    lines.append("")
    return "\n".join(lines)
