"""
ETL Guardrails for MAROON-ETL.

Custom guardrails using NeMoGuardrails pattern:
(a) No secrets in main lake
(b) PII routes to restricted bucket
(c) Binary noise excluded (Chromium/Electron > 10MB)
(d) File size limits enforced
(e) Valid document classification required
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..config.settings import ETLConfig
from ..classify.ontology_bridge import (
    NeMoGuardrails,
    Rail,
    RailType,
    Severity,
)


class ETLGuardrails:
    """
    ETL-specific guardrails built on Shafanna's NeMoGuardrails engine.
    Prevents data quality and security issues in the pipeline.
    """

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self.engine = NeMoGuardrails()
        self._register_etl_rails()

    def _register_etl_rails(self):
        """Register all ETL-specific guardrails."""

        # ─── Rail A: No secrets in main lake ─────────────────────────
        def check_no_secrets(data: Any, ctx: dict) -> bool:
            """Check that content doesn't contain secrets."""
            content = ""
            if isinstance(data, dict):
                content = data.get("content", "")
                if not content:
                    content = str(data.get("file_path", ""))
            elif isinstance(data, str):
                content = data

            if not content:
                return True

            secret_patterns = [
                r"(?i)(api[_-]?key|apikey)\s*[=:]\s*['\"]?[\w\-]{10,}",
                r"(?i)(secret|password|passwd)\s*[=:]\s*['\"]?[\w\-]{8,}",
                r"(?i)(token|access_token)\s*[=:]\s*['\"]?[\w\-]{10,}",
                r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[\w\-/+=]+",
                r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
                # AWS access key IDs (20 char, starts with AKIA)
                r"AKIA[A-Z0-9]{16}",
                # JWT tokens (base64url encoded header.payload)
                r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}",
                # Slack tokens
                r"xox[bpras]-[A-Za-z0-9\-]{10,}",
            ]

            for pattern in secret_patterns:
                if re.search(pattern, content):
                    return False
            return True

        self.engine.register_rail(Rail(
            name="etl_no_secrets_in_main",
            rail_type=RailType.SAFETY,
            severity=Severity.BLOCK,
            description="No secrets (API keys, passwords, tokens, private keys) in main lake",
            check_fn=check_no_secrets,
        ))

        # ─── Rail B: PII routes to restricted ────────────────────────
        def check_pii_routing(data: Any, ctx: dict) -> bool:
            """Check that PII files are routed to restricted bucket."""
            if not isinstance(data, dict):
                return True
            file_path = data.get("file_path", "")
            target_bucket = data.get("target_bucket", "")

            # If file has PII indicators (case-insensitive), must go to restricted bucket
            path_lower = file_path.lower()
            for pattern in self.config.PII_PATTERNS:
                if pattern.lower() in path_lower:
                    return target_bucket == self.config.RESTRICTED_BUCKET
            return True

        self.engine.register_rail(Rail(
            name="etl_pii_restricted_routing",
            rail_type=RailType.SAFETY,
            severity=Severity.BLOCK,
            description="PII-containing files (resume, Messages, Messenger, Facebook) must route to restricted bucket",
            check_fn=check_pii_routing,
        ))

        # ─── Rail C: Binary noise excluded ───────────────────────────
        def check_no_binary_noise(data: Any, ctx: dict) -> bool:
            """Check that binary noise is excluded."""
            if not isinstance(data, dict):
                return True
            file_name = data.get("file_name", data.get("file_path", ""))
            file_size = data.get("size", 0)

            name_lower = file_name.lower()
            size_mb = file_size / (1024 * 1024) if file_size > 0 else 0

            for pattern in self.config.BINARY_EXCLUSION_PATTERNS:
                if pattern.lower() in name_lower and size_mb > self.config.BINARY_SIZE_LIMIT_MB:
                    return False
            return True

        self.engine.register_rail(Rail(
            name="etl_no_binary_noise",
            rail_type=RailType.INPUT,
            severity=Severity.BLOCK,
            description="Chromium/Electron binaries > 10MB are excluded from pipeline",
            check_fn=check_no_binary_noise,
        ))

        # ─── Rail D: File size limits ────────────────────────────────
        def check_file_size(data: Any, ctx: dict) -> bool:
            """Enforce maximum file size for processing."""
            if not isinstance(data, dict):
                return True
            file_size = data.get("size", 0)
            # Max 100MB for any single file
            max_size = 100 * 1024 * 1024
            return file_size <= max_size

        self.engine.register_rail(Rail(
            name="etl_file_size_limit",
            rail_type=RailType.INPUT,
            severity=Severity.BLOCK,
            description="Files exceeding 100MB are blocked from processing",
            check_fn=check_file_size,
        ))

        # ─── Rail E: Valid document classification ────────────────────
        def check_valid_classification(data: Any, ctx: dict) -> bool:
            """Ensure document has a valid classification."""
            if not isinstance(data, dict):
                return True
            cluster = data.get("cluster", "")
            if not cluster:
                return True  # Not yet classified - OK
            return cluster in self.config.DOCUMENT_CLUSTERS

        self.engine.register_rail(Rail(
            name="etl_valid_classification",
            rail_type=RailType.SCHEMA,
            severity=Severity.WARN,
            description="Document classification must be one of the 8 valid clusters",
            check_fn=check_valid_classification,
        ))

    def validate_extraction(self, file_data: dict) -> dict:
        """Validate a file before extraction processing."""
        # Run input rails with the file data dict directly
        result = self.engine._run_rails(RailType.INPUT, file_data, file_data)
        return result

    def validate_content(self, content_data: dict) -> dict:
        """Validate content before loading to lake."""
        # Run safety rails (secrets check)
        result = self.engine._run_rails(RailType.SAFETY, content_data, content_data)
        return result

    def validate_routing(self, routing_data: dict) -> dict:
        """Validate bucket routing decision."""
        result = self.engine._run_rails(RailType.SAFETY, routing_data, routing_data)
        return result

    def validate_classification(self, classification_data: dict) -> dict:
        """Validate classification output."""
        result = self.engine._run_rails(RailType.SCHEMA, classification_data, classification_data)
        return result

    def get_rail_names(self) -> list[str]:
        """Get all registered ETL rail names."""
        return [name for name in self.engine.get_rail_names() if name.startswith("etl_")]

    @property
    def stats(self) -> dict:
        """Get guardrails statistics."""
        return self.engine.stats
