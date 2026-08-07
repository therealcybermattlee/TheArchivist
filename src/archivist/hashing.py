"""Content hashing (exact) and perceptual hashing (similarity).

- `sha256_file` streams the file so large videos never load into memory.
- `perceptual_hash` computes a scipy-free dHash for still images (stored in the
  catalog's `phash` column for later near-duplicate matching). Videos and
  un-openable images return None; exact-hash dedup still covers them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1024 * 1024  # 1 MiB
_EDGE = 1024 * 1024   # quick-hash reads this many bytes from head and tail

try:
    from PIL import Image  # type: ignore

    _PIL = True
except Exception:  # pragma: no cover - optional dependency
    _PIL = False


def sha256_file(path: Path) -> str:
    """Full byte-exact content hash (reads the whole file)."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def quick_hash(path: Path) -> str:
    """Cheap identity: file size + first/last 1 MiB. Reads <=2 MiB regardless of
    file size, so it scales to a multi-TB video archive over SMB.

    Strong enough to group candidates; confirm true duplicates with sha256_file.
    For files <=2 MiB this reads the whole file, so it is exact for small files.
    """
    size = path.stat().st_size
    h = hashlib.sha256()
    h.update(str(size).encode())
    with path.open("rb") as fh:
        h.update(fh.read(_EDGE))
        if size > 2 * _EDGE:
            fh.seek(-_EDGE, 2)  # from end
            h.update(fh.read(_EDGE))
    return h.hexdigest()


def perceptual_hash(path: Path) -> str | None:
    """dHash: 9x8 grayscale, compare horizontally adjacent pixels -> 64-bit hex."""
    if not _PIL:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("L").resize((9, 8), Image.LANCZOS)
            px = im.tobytes()  # mode "L": one byte per pixel, row-major
    except Exception:
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            left = px[row * 9 + col]
            right = px[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:016x}"


def hamming(a: str, b: str) -> int:
    """Bit distance between two hex perceptual hashes (for dedupe later)."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")
