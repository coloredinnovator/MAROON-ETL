"""
MAROON-ETL Configuration.

All pipeline configuration: buckets, patterns, precedence rules.
Budget: UNDER $0.10/month. Zero-spend posture.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class ETLConfig:
    """Immutable configuration for the MAROON-ETL pipeline."""

    # ---- S3 Buckets ----
    MAIN_BUCKET: str = "maroon-datalake-496411573616-usw2"
    RESTRICTED_BUCKET: str = "maroon-datalake-restricted-496411573616-usw2"
    AWS_REGION: str = "us-west-2"
    AWS_ACCOUNT_ID: str = "496411573616"

    # ---- S3 Layout (data lake zones) ----
    RAW_PREFIX: str = "raw/"
    STAGED_PREFIX: str = "staged/"
    CURATED_PREFIX: str = "curated/"
    MANIFESTS_PREFIX: str = "_manifests/"
    AUDIT_PREFIX: str = "_manifests/audit/"

    # ---- Google Drive Source ----
    GDRIVE_FOLDER_ID: str = "1I43aPmvEJmUfbeDOYkzLh9gFXdkp_gh_"
    GDRIVE_OWNER: str = "wffoodgroup@gmail.com"

    # ---- Exclusion Patterns (files to skip) ----
    EXCLUSION_PATTERNS: tuple = (
        ".env",
        "kiro_oauth_config.json",
        ".git/",
        ".git",
        ".thumbnails",
    )

    # Chromium/Electron binary patterns (anything > 10MB or matching these)
    BINARY_EXCLUSION_PATTERNS: tuple = (
        "chromium",
        "electron",
        "chrome-linux",
        "chrome-win",
        "node_modules/.cache",
    )

    BINARY_SIZE_LIMIT_MB: int = 10

    # ---- PII Routing Patterns (route to restricted bucket) ----
    PII_PATTERNS: tuple = (
        "resume",
        "Messages",
        "Messenger",
        "Facebook",
    )

    # ---- Format Precedence (higher = preferred canonical) ----
    # When duplicates detected, keep the highest precedence format
    FORMAT_PRECEDENCE: tuple = (
        "application/vnd.google-apps.document",  # Google Doc (highest)
        "text/markdown",                          # .md
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/pdf",                        # PDF (lowest)
    )

    FORMAT_PRECEDENCE_LABELS: tuple = (
        "Google Doc",
        ".md",
        ".docx",
        "PDF",
    )

    # ---- Deduplication ----
    EXPECTED_DEDUP_RATIO: float = 0.65  # 60-70% duplicates expected

    # ---- Document Classification Clusters ----
    DOCUMENT_CLUSTERS: tuple = (
        "Business/Strategy",
        "Technical/Code",
        "Infra repo mirror",
        "Legal/Healthcare",
        "Marketing/Ops",
        "Ingest dumpster",
        "Device backup",
        "Staging/disposal",
    )

    # ---- Lifecycle Rules ----
    RAW_GLACIER_TRANSITION_DAYS: int = 90

    # ---- Feature Flags ----
    # When True, use BedrockDeepSeek for AI-assisted classification.
    # When False (default), classification is purely rule-based keyword matching.
    # Upgrade path: set MAROON_USE_AI_CLASSIFICATION=true once Bedrock costs
    # are acceptable and the DeepSeek model is validated against the 8 clusters.
    USE_AI_CLASSIFICATION: bool = False

    # ---- Encryption ----
    ENCRYPTION_METHOD: str = "AES256"  # SSE-S3

    # ---- Auth ----
    AUTH_METHOD: str = "OIDC"  # Zero stored credentials

    @classmethod
    def from_env(cls) -> "ETLConfig":
        """Create config with environment variable overrides."""
        ai_flag = os.environ.get("MAROON_USE_AI_CLASSIFICATION", "").lower()
        return cls(
            MAIN_BUCKET=os.environ.get(
                "MAROON_MAIN_BUCKET", cls.MAIN_BUCKET
            ),
            RESTRICTED_BUCKET=os.environ.get(
                "MAROON_RESTRICTED_BUCKET", cls.RESTRICTED_BUCKET
            ),
            AWS_REGION=os.environ.get("AWS_REGION", cls.AWS_REGION),
            GDRIVE_FOLDER_ID=os.environ.get(
                "MAROON_GDRIVE_FOLDER_ID", cls.GDRIVE_FOLDER_ID
            ),
            USE_AI_CLASSIFICATION=ai_flag in ("true", "1", "yes"),
        )

    def is_excluded(self, file_path: str, file_size_bytes: int = 0) -> bool:
        """
        Check if a file should be excluded from processing.

        Path-based exclusion patterns (EXCLUSION_PATTERNS) always apply.
        Binary exclusion patterns (BINARY_EXCLUSION_PATTERNS) only apply
        when the file exceeds BINARY_SIZE_LIMIT_MB, preventing false
        exclusion of small text files that happen to contain binary
        pattern keywords (e.g. 'chromium-notes.txt').

        Args:
            file_path: Path or filename to check.
            file_size_bytes: File size in bytes. Required for binary
                pattern matching. Defaults to 0 (skip binary check).
        """
        path_lower = file_path.lower()
        for pattern in self.EXCLUSION_PATTERNS:
            if pattern.lower() in path_lower:
                return True
        # Binary exclusion patterns only apply above the size threshold
        size_mb = file_size_bytes / (1024 * 1024) if file_size_bytes > 0 else 0
        if size_mb > self.BINARY_SIZE_LIMIT_MB:
            for pattern in self.BINARY_EXCLUSION_PATTERNS:
                if pattern.lower() in path_lower:
                    return True
        return False

    def is_pii(self, file_path: str) -> bool:
        """
        Check if a file should be routed to the restricted bucket.

        Uses case-insensitive substring matching so that paths like
        'Resume_2024.pdf' and 'RESUME.docx' are correctly detected.
        """
        path_lower = file_path.lower()
        for pattern in self.PII_PATTERNS:
            if pattern.lower() in path_lower:
                return True
        return False

    def get_format_precedence(self, mime_type: str) -> int:
        """Get the precedence score for a format (higher = better)."""
        try:
            idx = self.FORMAT_PRECEDENCE.index(mime_type)
            return len(self.FORMAT_PRECEDENCE) - idx
        except ValueError:
            return 0  # Unknown format, lowest precedence
