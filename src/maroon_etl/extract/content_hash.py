"""
Content Hashing for deduplication.

Uses SHA-256 content-addressable hashing following Shafanna's MerkleDAG pattern.
Every document gets a deterministic hash based on its content.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Optional, Union


class ContentHasher:
    """
    SHA-256 content hashing for document deduplication.
    Follows Shafanna's merkle.py _content_hash pattern.
    """

    @staticmethod
    def hash_bytes(data: bytes) -> str:
        """Compute SHA-256 hash of raw bytes."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def hash_string(text: str) -> str:
        """Compute SHA-256 hash of a string."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_dict(data: dict) -> str:
        """
        Compute SHA-256 hash of a dictionary.
        Uses canonical JSON serialization (sorted keys, no whitespace)
        for deterministic output - same as Shafanna's _content_hash.
        """
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def hash_file(file_path: Union[str, Path]) -> str:
        """Compute SHA-256 hash of a file's contents."""
        sha = hashlib.sha256()
        path = Path(file_path)
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def hash_content(content: Union[bytes, str, dict]) -> str:
        """
        Hash any content type. Dispatches to appropriate method.

        Args:
            content: bytes, string, or dict to hash.

        Returns:
            SHA-256 hex digest string.
        """
        if isinstance(content, bytes):
            return ContentHasher.hash_bytes(content)
        elif isinstance(content, str):
            return ContentHasher.hash_string(content)
        elif isinstance(content, dict):
            return ContentHasher.hash_dict(content)
        else:
            # Fallback: serialize as JSON
            canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def verify(content: Union[bytes, str, dict], expected_hash: str) -> bool:
        """Verify content matches an expected hash."""
        actual = ContentHasher.hash_content(content)
        return actual == expected_hash
