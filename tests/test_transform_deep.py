"""
Deep tests for MAROON-ETL transform layer.
Tests: dedup with real duplicate content, format precedence,
PII router with compound paths, secret pattern detection,
binary filtering at 10MB boundary.
"""

import sys
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "vendor" / "shafanna"))


class TestDedupRealDuplicates:
    """Test dedup engine with actual duplicate content scenarios."""

    def test_same_bytes_different_names_detected(self):
        """Two files with same content but different names are duplicates."""
        from maroon_etl.transform.dedup import DedupEngine
        from maroon_etl.extract.content_hash import ContentHasher

        engine = DedupEngine()
        content = b"Shared document content that appears in multiple files."
        content_hash = ContentHasher.hash_bytes(content)

        engine.index_file("docs/version1.md", {
            "content_hash": content_hash,
            "mime_type": "text/markdown",
            "size": len(content),
        })
        engine.index_file("backup/version1-copy.md", {
            "content_hash": content_hash,
            "mime_type": "text/markdown",
            "size": len(content),
        })

        records = engine.deduplicate()
        assert engine.stats["duplicate_files"] == 1
        assert engine.stats["unique_files"] == 1
        assert engine.stats["dedup_ratio"] == 0.5

    def test_three_duplicates_one_canonical(self):
        """Three files with same content produces one canonical and two dupes."""
        from maroon_etl.transform.dedup import DedupEngine
        from maroon_etl.extract.content_hash import ContentHasher

        engine = DedupEngine()
        content = b"Triple duplicate content."
        h = ContentHasher.hash_bytes(content)

        engine.index_file("a.md", {"content_hash": h, "mime_type": "text/markdown", "size": 24})
        engine.index_file("b.md", {"content_hash": h, "mime_type": "text/markdown", "size": 24})
        engine.index_file("c.md", {"content_hash": h, "mime_type": "text/markdown", "size": 24})

        records = engine.deduplicate()
        assert engine.stats["duplicate_files"] == 2
        assert engine.stats["unique_files"] == 1
        assert len(records) == 1
        assert records[0].duplicate_count == 2

    def test_no_false_positives(self):
        """Different content should not be flagged as duplicates."""
        from maroon_etl.transform.dedup import DedupEngine
        from maroon_etl.extract.content_hash import ContentHasher

        engine = DedupEngine()
        for i in range(5):
            content = f"Unique content number {i}".encode()
            h = ContentHasher.hash_bytes(content)
            engine.index_file(f"file_{i}.md", {
                "content_hash": h,
                "mime_type": "text/markdown",
                "size": len(content),
            })

        records = engine.deduplicate()
        assert engine.stats["duplicate_files"] == 0
        assert engine.stats["unique_files"] == 5
        assert len(records) == 5

    def test_is_duplicate_check(self):
        """is_duplicate returns True for previously indexed hashes."""
        from maroon_etl.transform.dedup import DedupEngine
        from maroon_etl.extract.content_hash import ContentHasher

        engine = DedupEngine()
        h = ContentHasher.hash_bytes(b"test content")
        engine.index_file("test.md", {"content_hash": h, "mime_type": "text/markdown", "size": 12})

        assert engine.is_duplicate(h) is True
        assert engine.is_duplicate("nonexistent_hash") is False


class TestFormatPrecedence:
    """Test format precedence selection for canonical versions."""

    def test_google_doc_preferred_over_markdown(self):
        """Google Doc format wins over markdown for canonical selection."""
        from maroon_etl.transform.dedup import DedupEngine
        from maroon_etl.extract.content_hash import ContentHasher

        engine = DedupEngine()
        content = b"Shared content across formats."
        h = ContentHasher.hash_bytes(content)

        engine.index_file("doc.md", {
            "content_hash": h,
            "mime_type": "text/markdown",
            "size": len(content),
        })
        engine.index_file("doc-gdoc", {
            "content_hash": h,
            "mime_type": "application/vnd.google-apps.document",
            "size": len(content),
        })

        records = engine.deduplicate()
        assert records[0].canonical_file == "doc-gdoc"
        assert records[0].canonical_mime == "application/vnd.google-apps.document"

    def test_markdown_preferred_over_pdf(self):
        """Markdown wins over PDF when both exist."""
        from maroon_etl.transform.dedup import DedupEngine
        from maroon_etl.extract.content_hash import ContentHasher

        engine = DedupEngine()
        h = ContentHasher.hash_bytes(b"document content")

        engine.index_file("doc.pdf", {
            "content_hash": h,
            "mime_type": "application/pdf",
            "size": 100,
        })
        engine.index_file("doc.md", {
            "content_hash": h,
            "mime_type": "text/markdown",
            "size": 100,
        })

        records = engine.deduplicate()
        assert records[0].canonical_file == "doc.md"

    def test_unknown_format_lowest_precedence(self):
        """Unknown MIME types have lowest precedence."""
        from maroon_etl.transform.dedup import DedupEngine
        from maroon_etl.extract.content_hash import ContentHasher

        engine = DedupEngine()
        h = ContentHasher.hash_bytes(b"content")

        engine.index_file("file.bin", {
            "content_hash": h,
            "mime_type": "application/octet-stream",
            "size": 7,
        })
        engine.index_file("file.pdf", {
            "content_hash": h,
            "mime_type": "application/pdf",
            "size": 7,
        })

        records = engine.deduplicate()
        assert records[0].canonical_file == "file.pdf"


class TestPIIRouterCompoundPaths:
    """Test PII router with compound/nested paths."""

    def test_messages_in_nested_path(self):
        """PII detected in compound path: project/Messages/thread.json."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("project/Messages/thread.json")
        assert result["action"] == "route_restricted"
        assert "Messages" in result["reason"]

    def test_messenger_deep_nested(self):
        """Messenger path in deep directory tree triggers PII routing."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("backups/2024/social/Messenger/conversation.html")
        assert result["action"] == "route_restricted"

    def test_facebook_export(self):
        """Facebook data export gets routed to restricted bucket."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("exports/Facebook/posts/timeline.json")
        assert result["action"] == "route_restricted"
        assert result["bucket"] == "maroon-datalake-restricted-496411573616-usw2"

    def test_resume_in_any_position(self):
        """Resume detection works anywhere in the path."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("applications/john_resume_2024.pdf")
        assert result["action"] == "route_restricted"

    def test_clean_compound_path(self):
        """Normal compound paths do not trigger PII routing."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("projects/infrastructure/terraform/main.tf")
        assert result["action"] == "route_main"
        assert result["bucket"] == "maroon-datalake-496411573616-usw2"


class TestSecretPatternDetection:
    """Test secret detection patterns in content."""

    def test_aws_secret_access_key_detected(self):
        """AWS_SECRET_ACCESS_KEY in content triggers secret detection."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        content = "AWS_SECRET_ACCESS_KEY = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = router.route("config.txt", content=content)
        assert result["action"] == "block"

    def test_private_key_block_detected(self):
        """-----BEGIN PRIVATE KEY----- blocks are caught."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        content = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/ygWep4PAtGoR
-----END RSA PRIVATE KEY-----"""
        result = router.route("server.key", content=content)
        assert result["action"] == "block"

    def test_bearer_token_detected(self):
        """Bearer/access tokens in content are detected."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        content = "access_token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        result = router.route("token.txt", content=content)
        assert result["action"] == "block"

    def test_env_file_content_detected(self):
        """.env style KEY=value content with secrets is blocked."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        content = """DATABASE_URL=postgres://user:pass@host/db
API_KEY = sk-proj-1234567890abcdef
SECRET = mysupersecretvalue123"""
        result = router.route("app-config.txt", content=content)
        assert result["action"] == "block"

    def test_clean_content_not_blocked(self):
        """Normal document content should not trigger secret detection."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        content = """# Project Documentation
This document describes the architecture of our system.
It uses AWS services for cloud infrastructure."""
        result = router.route("architecture.md", content=content)
        assert result["action"] == "route_main"

    def test_stats_tracking(self):
        """Router tracks scanning statistics correctly."""
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        router.route("safe.md", content="normal content")
        router.route("pii/resume.pdf")
        router.route("keys.txt", content="api_key = abc1234567890")

        assert router.stats["files_scanned"] == 3
        assert router.stats["pii_detected"] == 1
        assert router.stats["secrets_detected"] == 1


class TestBinaryFiltering:
    """Test binary noise filtering at size boundaries."""

    def test_exactly_10mb_chromium_excluded(self):
        """Chromium binary at exactly 10MB is NOT excluded (threshold is >10MB).
        The size gate requires strictly exceeding the limit."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        # Exactly 10MB does not exceed the 10MB limit
        file_meta = {"name": "chromium-browser", "size": "10485760"}
        assert extractor._should_exclude(file_meta) is False

    def test_over_10mb_chromium_excluded(self):
        """Chromium binary over 10MB should be excluded."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        # 11MB worth
        file_meta = {"name": "chromium-browser", "size": str(11 * 1024 * 1024)}
        assert extractor._should_exclude(file_meta) is True

    def test_small_chromium_reference_not_excluded(self):
        """Small file with 'chromium' in name should NOT be excluded.
        Binary exclusion patterns only apply above the size threshold,
        preventing false exclusion of small text files like 'chromium-notes.txt'."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        # Without size info, binary patterns do not trigger exclusion
        assert config.is_excluded("chromium/notes.txt") is False
        # With size above threshold, it IS excluded
        assert config.is_excluded("chromium/notes.txt", file_size_bytes=50 * 1024 * 1024) is True

    def test_large_non_binary_not_excluded(self):
        """Large file without binary pattern names should not be excluded."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        file_meta = {"name": "large-dataset.csv", "size": str(50 * 1024 * 1024)}
        assert extractor._should_exclude(file_meta) is False
