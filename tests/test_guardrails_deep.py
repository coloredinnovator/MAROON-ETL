"""
Comprehensive guardrails tests for MAROON-ETL.
Tests: each rail individually (secrets, PII, binary, size, classification),
multiple secret patterns, large file simulation, stats tracking.
"""

import sys
from pathlib import Path

import pytest

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "vendor" / "shafanna"))


class TestSecretsRail:
    """Test the etl_no_secrets_in_main rail individually."""

    def test_api_key_blocked(self):
        """API key in content triggers BLOCK."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "content": "api_key = sk-proj-abcdefgh1234567890",
            "file_path": "config.yaml",
        })
        assert result["blocked"] is True

    def test_aws_key_blocked(self):
        """AWS secret access key triggers BLOCK."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "content": "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCY",
            "file_path": "credentials",
        })
        assert result["blocked"] is True

    def test_private_key_blocked(self):
        """RSA private key blocks content loading."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAJ..."
        result = rails.validate_content({
            "content": content,
            "file_path": "server.pem",
        })
        assert result["blocked"] is True

    def test_github_token_blocked(self):
        """GitHub personal access token in content triggers BLOCK."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "content": "token = ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZab",
            "file_path": "git-config",
        })
        assert result["blocked"] is True

    def test_env_password_blocked(self):
        """Password in .env style content triggers BLOCK."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "content": "password = SuperSecret123!",
            "file_path": ".env.local",
        })
        assert result["blocked"] is True

    def test_clean_content_passes(self):
        """Normal content without secrets passes safety rails."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "content": "# Architecture\nThis document explains our system design.",
            "file_path": "architecture.md",
        })
        assert result["blocked"] is False


class TestPIIRoutingRail:
    """Test the etl_pii_restricted_routing rail individually."""

    def test_pii_file_to_main_bucket_blocked(self):
        """PII file routed to main bucket should be blocked."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "file_path": "resume_john_doe.pdf",
            "target_bucket": "maroon-datalake-496411573616-usw2",
        })
        assert result["blocked"] is True

    def test_pii_file_to_restricted_bucket_passes(self):
        """PII file routed to restricted bucket passes."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "file_path": "resume_john_doe.pdf",
            "target_bucket": "maroon-datalake-restricted-496411573616-usw2",
        })
        assert result["blocked"] is False

    def test_normal_file_to_main_passes(self):
        """Normal file to main bucket passes PII rail."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_content({
            "file_path": "technical-spec.md",
            "target_bucket": "maroon-datalake-496411573616-usw2",
        })
        assert result["blocked"] is False


class TestBinaryNoiseRail:
    """Test the etl_no_binary_noise rail individually."""

    def test_large_chromium_blocked(self):
        """Large chromium binary triggers BLOCK."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_extraction({
            "file_name": "chromium-linux64",
            "size": 50 * 1024 * 1024,  # 50MB
        })
        assert result["blocked"] is True

    def test_large_electron_blocked(self):
        """Large electron binary triggers BLOCK."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_extraction({
            "file_name": "electron-framework.app",
            "size": 15 * 1024 * 1024,  # 15MB
        })
        assert result["blocked"] is True

    def test_small_binary_passes(self):
        """Small binary file (under 10MB) passes even with binary name."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_extraction({
            "file_name": "chromium-notes.txt",
            "size": 1024,  # 1KB
        })
        assert result["blocked"] is False

    def test_large_normal_file_passes(self):
        """Large non-binary file passes the binary noise rail."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_extraction({
            "file_name": "huge-dataset.csv",
            "size": 50 * 1024 * 1024,  # 50MB
        })
        assert result["blocked"] is False


class TestFileSizeRail:
    """Test the etl_file_size_limit rail individually."""

    def test_over_100mb_blocked(self):
        """Files over 100MB should be blocked."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_extraction({
            "file_name": "massive-file.bin",
            "size": 101 * 1024 * 1024,  # 101MB
        })
        assert result["blocked"] is True

    def test_exactly_100mb_passes(self):
        """File at exactly 100MB passes (limit is <=)."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_extraction({
            "file_name": "large-file.zip",
            "size": 100 * 1024 * 1024,  # 100MB
        })
        assert result["blocked"] is False

    def test_normal_file_passes(self):
        """Normal-sized file passes size check."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_extraction({
            "file_name": "document.pdf",
            "size": 5 * 1024 * 1024,  # 5MB
        })
        assert result["blocked"] is False


class TestClassificationRail:
    """Test the etl_valid_classification rail individually."""

    def test_valid_cluster_passes(self):
        """Valid cluster name passes classification rail."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_classification({
            "cluster": "Business/Strategy",
        })
        assert result["passed"] is True

    def test_invalid_cluster_warns(self):
        """Invalid cluster name triggers WARN (not block)."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_classification({
            "cluster": "Nonexistent/Category",
        })
        # Classification rail is WARN severity, not BLOCK
        assert result["blocked"] is False
        assert len(result["violations"]) > 0

    def test_empty_cluster_passes(self):
        """Empty cluster (not yet classified) passes."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        result = rails.validate_classification({
            "cluster": "",
        })
        assert result["passed"] is True

    def test_all_valid_clusters(self):
        """All 8 valid clusters pass the classification rail."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        rails = ETLGuardrails()

        for cluster in config.DOCUMENT_CLUSTERS:
            result = rails.validate_classification({"cluster": cluster})
            assert result["passed"] is True, f"Cluster '{cluster}' should pass"


class TestGuardrailsStatsTracking:
    """Test that guardrails track statistics correctly."""

    def test_stats_increment_on_checks(self):
        """Stats are incremented as rails are checked."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()

        rails.validate_extraction({"file_name": "doc.md", "size": 1024})
        rails.validate_content({"content": "safe text", "file_path": "doc.md"})

        stats = rails.stats
        assert stats["checks"] > 0
        assert stats["rails_registered"] > 0

    def test_violations_counted(self):
        """Violations are counted in stats."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()

        # Trigger a violation
        rails.validate_content({
            "content": "password = mysecret12345678",
            "file_path": "leaked.txt",
        })

        stats = rails.stats
        assert stats["violations"] > 0

    def test_rail_names_listed(self):
        """All ETL rails can be listed by name."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()
        names = rails.get_rail_names()
        assert "etl_no_secrets_in_main" in names
        assert "etl_pii_restricted_routing" in names
        assert "etl_no_binary_noise" in names
        assert "etl_file_size_limit" in names
        assert "etl_valid_classification" in names

    def test_multiple_secrets_all_blocked(self):
        """Multiple different secret types all trigger blocks."""
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        rails = ETLGuardrails()

        secrets = [
            "api_key = sk-1234567890abcdefghij",
            "aws_secret_access_key = wJalrXUtn/K7MDENG",
            "-----BEGIN PRIVATE KEY-----\ndata",
            "password = SuperSecret123!",
            "access_token = ghp_aBcDeFgHiJkLmNoPq",
        ]

        for secret in secrets:
            result = rails.validate_content({
                "content": secret,
                "file_path": "test.txt",
            })
            assert result["blocked"] is True, f"Should block: {secret[:30]}..."
