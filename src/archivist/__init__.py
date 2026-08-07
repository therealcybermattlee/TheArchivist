"""The Archivist — personal media-archival CLI for the Lee Family library.

Safety invariant: source data is read-only, always. All media flows
  source --(copy)--> work_root (stage/decide) --(copy+verify)--> archive_root.
The archive (archive_root) is the only write target.
"""

__version__ = "0.1.0"
