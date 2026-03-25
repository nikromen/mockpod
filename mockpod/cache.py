from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from mockpod.constants import BUILD_HASHES_FILE

logger = logging.getLogger(__name__)


def compute_hash(package_path: Path) -> str:
    """SHA256 of the package and all files in its directory."""
    h = hashlib.sha256()
    pkg_dir = package_path.parent

    files = sorted(f for f in pkg_dir.iterdir() if f.is_file() and not f.is_symlink())
    for f in files:
        h.update(f.name.encode())
        h.update(f.read_bytes())

    return h.hexdigest()


def _hashes_path(cache_dir: Path, chroot: str) -> Path:
    return cache_dir / chroot / BUILD_HASHES_FILE


def _load_hashes(cache_dir: Path, chroot: str) -> dict[str, str]:
    path = _hashes_path(cache_dir, chroot)
    if not path.exists():
        return {}
    with open(path) as f:
        data: dict[str, str] = json.load(f)
    return data


def _save_hashes(cache_dir: Path, chroot: str, hashes: dict[str, str]) -> None:
    path = _hashes_path(cache_dir, chroot)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(hashes, f, indent=2)


def needs_rebuild(cache_dir: Path, package: str, chroot: str, package_path: Path) -> bool:
    """Return True if the package needs a rebuild (sources changed or no previous build)."""
    current = compute_hash(package_path)
    stored = _load_hashes(cache_dir, chroot)
    previous = stored.get(package)

    if previous == current:
        logger.debug("%s/%s: hash unchanged (%s)", chroot, package, current[:12])
        return False

    logger.debug("%s/%s: hash changed %s -> %s", chroot, package, previous, current[:12])
    return True


def save_hash(cache_dir: Path, package: str, chroot: str, spec_file: Path) -> None:
    """Store the current hash after a successful build."""
    current = compute_hash(spec_file)
    hashes = _load_hashes(cache_dir, chroot)
    hashes[package] = current
    _save_hashes(cache_dir, chroot, hashes)
