from __future__ import annotations

from pathlib import Path

from mockpod.cache import compute_hash, needs_rebuild, save_hash


class TestComputeHash:
    def test_deterministic(self, tmp_project: Path) -> None:
        spec = tmp_project / "testpkg" / "testpkg.spec"
        h1 = compute_hash(spec)
        h2 = compute_hash(spec)
        assert h1 == h2

    def test_changes_with_content(self, tmp_project: Path) -> None:
        spec = tmp_project / "testpkg" / "testpkg.spec"
        h1 = compute_hash(spec)

        cfg = tmp_project / "testpkg" / "testpkg.cfg"
        cfg.write_text("key=changed\n")
        h2 = compute_hash(spec)
        assert h1 != h2

    def test_changes_with_spec(self, tmp_project: Path) -> None:
        spec = tmp_project / "testpkg" / "testpkg.spec"
        h1 = compute_hash(spec)

        spec.write_text(spec.read_text() + "# comment\n")
        h2 = compute_hash(spec)
        assert h1 != h2

    def test_hex_string(self, tmp_project: Path) -> None:
        spec = tmp_project / "testpkg" / "testpkg.spec"
        h = compute_hash(spec)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestNeedsRebuild:
    def test_no_previous_build(self, tmp_project: Path, cache_dir: Path) -> None:
        spec = tmp_project / "testpkg" / "testpkg.spec"
        assert needs_rebuild(cache_dir, "testpkg", "fedora-43-x86_64", spec)

    def test_after_save(self, tmp_project: Path, cache_dir: Path) -> None:
        spec = tmp_project / "testpkg" / "testpkg.spec"
        chroot = "fedora-43-x86_64"

        save_hash(cache_dir, "testpkg", chroot, spec)
        assert not needs_rebuild(cache_dir, "testpkg", chroot, spec)

    def test_after_change(self, tmp_project: Path, cache_dir: Path) -> None:
        spec = tmp_project / "testpkg" / "testpkg.spec"
        chroot = "fedora-43-x86_64"

        save_hash(cache_dir, "testpkg", chroot, spec)

        spec.write_text(spec.read_text().replace("1.0", "2.0"))
        assert needs_rebuild(cache_dir, "testpkg", chroot, spec)
