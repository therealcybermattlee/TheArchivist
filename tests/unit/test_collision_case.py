"""Unit tests: portable collision policy (004 FR-009 + PLAN.md §E same-hash rule)."""

from pathlib import Path

from archivist.ingest import _case_match, _collision_free


def _file(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class TestCaseMatch:
    def test_no_dir_no_match(self, tmp_path: Path):
        assert _case_match(tmp_path / "nope" / "a.jpg") is None

    def test_exact_and_case_variant(self, tmp_path: Path):
        _file(tmp_path / "IMG_1.JPG", b"x")
        assert _case_match(tmp_path / "IMG_1.JPG") is not None
        assert _case_match(tmp_path / "img_1.jpg").name == "IMG_1.JPG"
        assert _case_match(tmp_path / "other.jpg") is None


class TestCollisionFree:
    def test_free_destination_passes_through(self, tmp_path: Path):
        src = _file(tmp_path / "src" / "a.jpg", b"content")
        dst, dup = _collision_free(tmp_path / "arc" / "a.jpg", src, "ffff0000", set())
        assert dst == tmp_path / "arc" / "a.jpg" and dup is None

    def test_case_twin_different_content_gets_suffix(self, tmp_path: Path):
        _file(tmp_path / "arc" / "IMG_1.JPG", b"existing-bytes")
        src = _file(tmp_path / "src" / "img_1.jpg", b"different-bytes")
        dst, dup = _collision_free(tmp_path / "arc" / "img_1.jpg", src, "abcd1234", set())
        assert dup is None
        assert dst.name == "img_1__abcd1234.jpg"  # suffixed, never a case-twin

    def test_case_twin_byte_identical_is_duplicate_skip(self, tmp_path: Path):
        existing = _file(tmp_path / "arc" / "IMG_1.JPG", b"same-bytes")
        src = _file(tmp_path / "src" / "img_1.jpg", b"same-bytes")
        dst, dup = _collision_free(tmp_path / "arc" / "img_1.jpg", src, "abcd1234", set())
        assert dst is None and dup == str(existing)

    def test_same_name_same_hash_existing_dst_skips(self, tmp_path: Path):
        # PLAN.md §E: identical bytes already at the exact destination →
        # duplicate skip even with an empty/incomplete catalog.
        existing = _file(tmp_path / "arc" / "a.jpg", b"identical")
        src = _file(tmp_path / "src" / "a.jpg", b"identical")
        dst, dup = _collision_free(tmp_path / "arc" / "a.jpg", src, "ffff0000", set())
        assert dst is None and dup == str(existing)

    def test_planned_collision_case_insensitive(self, tmp_path: Path):
        src = _file(tmp_path / "src" / "b.jpg", b"bytes-b")
        planned = {str(tmp_path / "arc" / "B.JPG").casefold()}
        dst, dup = _collision_free(tmp_path / "arc" / "b.jpg", src, "beef0001", planned)
        assert dup is None and dst.name == "b__beef0001.jpg"
