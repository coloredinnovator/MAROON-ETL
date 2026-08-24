"""
Deduplication Engine for MAROON-ETL.

Uses SHA-256 content hashes to identify duplicate documents.
Expected 60-70% duplication by volume in the Drive vault.
Selects canonical version based on format precedence:
    Google Doc > .md > .docx > PDF
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config.settings import ETLConfig
from ..extract.content_hash import ContentHasher


@dataclass
class DedupRecord:
    """A record of a deduplicated document group."""
    content_hash: str
    canonical_file: str
    canonical_mime: str
    duplicates: list[str] = field(default_factory=list)
    duplicate_count: int = 0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "content_hash": self.content_hash,
            "canonical_file": self.canonical_file,
            "canonical_mime": self.canonical_mime,
            "duplicates": self.duplicates,
            "duplicate_count": self.duplicate_count,
        }


class DedupEngine:
    """
    Deduplication engine using SHA-256 content hashes.
    Follows Shafanna's MerkleDAG content-addressable pattern.
    """

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self._hash_index: dict[str, list[dict]] = {}  # hash -> list of file metadata
        self.stats = {
            "total_files": 0,
            "unique_files": 0,
            "duplicate_files": 0,
            "dedup_ratio": 0.0,
            "bytes_saved": 0,
        }

    def index_file(self, file_path: str, metadata: dict) -> str:
        """
        Index a file by its content hash.

        Args:
            file_path: Path to the file (or logical name).
            metadata: File metadata dict (must include content_hash, mime_type).

        Returns:
            The content hash of the file.
        """
        content_hash = metadata.get("content_hash", "")
        if not content_hash:
            content_hash = ContentHasher.hash_file(file_path)

        entry = {
            "file_path": file_path,
            "content_hash": content_hash,
            "mime_type": metadata.get("mime_type", "unknown"),
            "size": metadata.get("size", 0),
            "modified_time": metadata.get("modified_time", ""),
            "original_name": metadata.get("original_name", file_path),
        }

        if content_hash not in self._hash_index:
            self._hash_index[content_hash] = []
        self._hash_index[content_hash].append(entry)
        self.stats["total_files"] += 1

        return content_hash

    def deduplicate(self) -> list[DedupRecord]:
        """
        Run deduplication. Returns list of DedupRecords.
        For each group of duplicates, selects canonical version
        based on format precedence.
        """
        records = []

        for content_hash, entries in self._hash_index.items():
            if len(entries) == 1:
                # Unique file - no dedup needed
                records.append(DedupRecord(
                    content_hash=content_hash,
                    canonical_file=entries[0]["file_path"],
                    canonical_mime=entries[0]["mime_type"],
                    duplicates=[],
                    duplicate_count=0,
                ))
                self.stats["unique_files"] += 1
            else:
                # Multiple entries with same hash - pick canonical
                canonical = self._select_canonical(entries)
                dupes = [
                    e["file_path"] for e in entries
                    if e["file_path"] != canonical["file_path"]
                ]
                records.append(DedupRecord(
                    content_hash=content_hash,
                    canonical_file=canonical["file_path"],
                    canonical_mime=canonical["mime_type"],
                    duplicates=dupes,
                    duplicate_count=len(dupes),
                ))
                self.stats["unique_files"] += 1
                self.stats["duplicate_files"] += len(dupes)
                self.stats["bytes_saved"] += sum(
                    e["size"] for e in entries
                    if e["file_path"] != canonical["file_path"]
                )

        # Calculate dedup ratio
        total = self.stats["total_files"]
        if total > 0:
            self.stats["dedup_ratio"] = self.stats["duplicate_files"] / total

        return records

    def _select_canonical(self, entries: list[dict]) -> dict:
        """
        Select the canonical version from a group of duplicates.
        Uses format precedence: Google Doc > .md > .docx > PDF
        """
        # Sort by format precedence (highest first)
        scored = []
        for entry in entries:
            precedence = self.config.get_format_precedence(entry["mime_type"])
            scored.append((precedence, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    def generate_manifest(self) -> dict:
        """Generate a deduplication manifest."""
        records = self.deduplicate() if not self.stats["unique_files"] else []
        # If already deduped, regenerate from index
        if not records:
            records = self.deduplicate()

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": self.stats,
            "records": [r.to_dict() for r in records],
        }

    def is_duplicate(self, content_hash: str) -> bool:
        """Check if a content hash has already been indexed."""
        return content_hash in self._hash_index

    def get_canonical(self, content_hash: str) -> Optional[str]:
        """Get the canonical file path for a content hash."""
        entries = self._hash_index.get(content_hash, [])
        if not entries:
            return None
        if len(entries) == 1:
            return entries[0]["file_path"]
        canonical = self._select_canonical(entries)
        return canonical["file_path"]

    def reset(self) -> None:
        """Reset the dedup engine state."""
        self._hash_index.clear()
        self.stats = {
            "total_files": 0,
            "unique_files": 0,
            "duplicate_files": 0,
            "dedup_ratio": 0.0,
            "bytes_saved": 0,
        }
