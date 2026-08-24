"""
Deep tests for MAROON-ETL extraction layer.
Tests: exclusion filtering edge cases, content hash determinism,
GDrive extractor with mocked API, file metadata sidecar generation.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "vendor" / "shafanna"))


class TestExclusionFilteringEdgeCases:
    """Test exclusion filtering with nested and tricky paths."""

    def test_nested_git_path_excluded(self):
        """Files inside .git subdirectories should be excluded."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert config.is_excluded("project/.git/objects/abc123")

    def test_dot_env_inside_subdirectory(self):
        """A .env file buried in a subdir should be excluded."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert config.is_excluded("deep/nested/path/.env")

    def test_env_substring_not_excluded(self):
        """A file named 'environment.md' should NOT be excluded (no .env match)."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        # 'environment.md' does not contain '.env' as a substring
        # Actually it doesn't contain '.env' -- the substring is 'env' not '.env'
        assert not config.is_excluded("environment.md")

    def test_chromium_binary_excluded(self):
        """Chromium binary pattern should be excluded when file is large."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        # Binary exclusion patterns only apply above size threshold
        assert config.is_excluded("chrome-linux/chrome", file_size_bytes=50 * 1024 * 1024)
        # Without size info (or small size), binary pattern alone does not exclude
        assert not config.is_excluded("chrome-linux/chrome")
        assert not config.is_excluded("chrome-linux/chrome", file_size_bytes=1024)

    def test_electron_binary_excluded(self):
        """Electron framework directory should be excluded when file is large."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        # Binary exclusion patterns only apply above size threshold
        assert config.is_excluded(
            "node_modules/electron/dist/electron",
            file_size_bytes=15 * 1024 * 1024,
        )
        # Small electron-named file is NOT excluded (fixes conflation bug)
        assert not config.is_excluded("node_modules/electron/dist/electron")

    def test_thumbnails_excluded(self):
        """Thumbnail directories should be excluded."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert config.is_excluded(".thumbnails/large/photo.png")

    def test_normal_file_not_excluded(self):
        """Normal documents should pass through without exclusion."""
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert not config.is_excluded("projects/strategy-doc.md")
        assert not config.is_excluded("reports/q4-financials.pdf")


class TestContentHashDeterminism:
    """Test that same content produces same hash regardless of filename."""

    def test_same_bytes_same_hash(self):
        """Identical byte content must produce identical hash."""
        from maroon_etl.extract.content_hash import ContentHasher
        content = b"This is a test document with specific content."
        hash_a = ContentHasher.hash_bytes(content)
        hash_b = ContentHasher.hash_bytes(content)
        assert hash_a == hash_b

    def test_same_content_different_filenames(self):
        """Same file content written to different filenames produces same hash."""
        from maroon_etl.extract.content_hash import ContentHasher
        content = b"Identical document content for dedup testing."

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f1:
            f1.write(content)
            path1 = f1.name

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f2:
            f2.write(content)
            path2 = f2.name

        try:
            hash1 = ContentHasher.hash_file(path1)
            hash2 = ContentHasher.hash_file(path2)
            assert hash1 == hash2
        finally:
            os.unlink(path1)
            os.unlink(path2)

    def test_different_content_different_hash(self):
        """Different content must produce different hashes."""
        from maroon_etl.extract.content_hash import ContentHasher
        hash_a = ContentHasher.hash_bytes(b"Content A")
        hash_b = ContentHasher.hash_bytes(b"Content B")
        assert hash_a != hash_b

    def test_dict_hash_deterministic(self):
        """Dictionary hashing is deterministic regardless of key insertion order."""
        from maroon_etl.extract.content_hash import ContentHasher
        dict_a = {"z_key": "value1", "a_key": "value2", "m_key": "value3"}
        dict_b = {"a_key": "value2", "m_key": "value3", "z_key": "value1"}
        assert ContentHasher.hash_dict(dict_a) == ContentHasher.hash_dict(dict_b)

    def test_hash_verify(self):
        """Verify method correctly validates content against stored hash."""
        from maroon_etl.extract.content_hash import ContentHasher
        content = b"verify this content"
        expected = ContentHasher.hash_bytes(content)
        assert ContentHasher.verify(content, expected) is True
        assert ContentHasher.verify(b"different content", expected) is False


class TestGDriveExtractorMocked:
    """Test GDrive extractor with mocked Drive API."""

    def test_extractor_initializes_with_config(self):
        """GDriveExtractor uses ETLConfig defaults."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        assert extractor.config.GDRIVE_FOLDER_ID == "1I43aPmvEJmUfbeDOYkzLh9gFXdkp_gh_"

    def test_should_exclude_env_file(self):
        """Extractor should exclude .env files."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        file_meta = {"name": ".env", "size": "100"}
        assert extractor._should_exclude(file_meta) is True

    def test_should_exclude_oauth_config(self):
        """Extractor should exclude OAuth config files."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        file_meta = {"name": "kiro_oauth_config.json", "size": "200"}
        assert extractor._should_exclude(file_meta) is True

    def test_should_not_exclude_document(self):
        """Extractor should not exclude normal documents."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        file_meta = {"name": "business-plan.md", "size": "5000"}
        assert extractor._should_exclude(file_meta) is False

    def test_google_doc_export_types(self):
        """Extractor knows which MIME types need export."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        assert "application/vnd.google-apps.document" in GDriveExtractor.EXPORT_TYPES
        assert "application/vnd.google-apps.spreadsheet" in GDriveExtractor.EXPORT_TYPES

    def test_extract_with_mocked_drive(self):
        """Full extraction flow with mocked Drive API responses."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor

        extractor = GDriveExtractor()

        # Mock the drive service
        mock_service = MagicMock()
        mock_files = MagicMock()
        mock_service.files.return_value = mock_files

        # Mock list response
        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "files": [
                {
                    "id": "file_001",
                    "name": "project-plan.md",
                    "mimeType": "text/markdown",
                    "size": "1024",
                    "modifiedTime": "2024-01-15T10:00:00Z",
                },
            ],
            "nextPageToken": None,
        }
        mock_files.list.return_value = mock_list

        # Mock download
        mock_get_media = MagicMock()
        mock_get_media.execute.return_value = b"# Project Plan\nThis is the plan."
        mock_files.get_media.return_value = mock_get_media

        extractor._drive_service = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            result = extractor.extract(output_dir=tmpdir)
            assert result["stats"]["files_discovered"] == 1
            assert result["stats"]["files_extracted"] == 1


class TestMetadataSidecar:
    """Test that file metadata JSON sidecars are generated correctly."""

    def test_sidecar_created_on_extract(self):
        """Extracting a file should create a .meta.json sidecar."""
        from maroon_etl.extract.gdrive_extractor import GDriveExtractor

        extractor = GDriveExtractor()
        mock_service = MagicMock()
        mock_files = MagicMock()
        mock_service.files.return_value = mock_files

        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "files": [
                {
                    "id": "file_sidecar_test",
                    "name": "notes.txt",
                    "mimeType": "text/plain",
                    "size": "512",
                    "modifiedTime": "2024-02-01T08:30:00Z",
                },
            ],
            "nextPageToken": None,
        }
        mock_files.list.return_value = mock_list

        mock_get_media = MagicMock()
        mock_get_media.execute.return_value = b"These are my notes."
        mock_files.get_media.return_value = mock_get_media

        extractor._drive_service = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            extractor.extract(output_dir=tmpdir)
            sidecar_path = Path(tmpdir) / "notes.txt.meta.json"
            assert sidecar_path.exists(), "Metadata sidecar should be created"
            meta = json.loads(sidecar_path.read_text())
            assert meta["source"] == "google_drive"
            assert meta["file_id"] == "file_sidecar_test"
            assert meta["original_name"] == "notes.txt"
            assert "content_hash" in meta
            assert len(meta["content_hash"]) == 64  # SHA-256 hex

    def test_sidecar_includes_content_hash(self):
        """Sidecar must contain a valid SHA-256 content hash."""
        from maroon_etl.extract.content_hash import ContentHasher
        content = b"These are my notes."
        expected_hash = ContentHasher.hash_bytes(content)

        from maroon_etl.extract.gdrive_extractor import GDriveExtractor
        extractor = GDriveExtractor()
        mock_service = MagicMock()
        mock_files = MagicMock()
        mock_service.files.return_value = mock_files

        mock_list = MagicMock()
        mock_list.execute.return_value = {
            "files": [{
                "id": "hash_test",
                "name": "doc.txt",
                "mimeType": "text/plain",
                "size": "19",
                "modifiedTime": "2024-03-01T00:00:00Z",
            }],
            "nextPageToken": None,
        }
        mock_files.list.return_value = mock_list

        mock_get_media = MagicMock()
        mock_get_media.execute.return_value = content
        mock_files.get_media.return_value = mock_get_media

        extractor._drive_service = mock_service

        with tempfile.TemporaryDirectory() as tmpdir:
            extractor.extract(output_dir=tmpdir)
            sidecar = json.loads((Path(tmpdir) / "doc.txt.meta.json").read_text())
            assert sidecar["content_hash"] == expected_hash
