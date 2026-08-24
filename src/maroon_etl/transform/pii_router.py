"""
PII Router for MAROON-ETL.

Detects files containing PII based on path patterns and routes them
to the restricted bucket (maroon-datalake-restricted-496411573616-usw2).

PII indicators:
- "resume" in path
- "Messages" in path
- "Messenger" in path
- "Facebook" in path

Also detects secrets patterns:
- .env file contents (API keys, passwords, tokens)
- OAuth config files
- Private keys
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..config.settings import ETLConfig


@dataclass
class PIIDetection:
    """Record of a PII detection event."""
    file_path: str
    detection_type: str  # "pii_path" or "secret_content"
    pattern_matched: str
    action: str  # "route_restricted" or "block"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "file_path": self.file_path,
            "detection_type": self.detection_type,
            "pattern_matched": self.pattern_matched,
            "action": self.action,
            "timestamp": self.timestamp,
        }


class PIIRouter:
    """
    Routes PII-containing files to the restricted bucket.
    Detects secrets and prevents them from entering the main lake.
    """

    # Patterns indicating secrets in content
    SECRET_PATTERNS = [
        r"(?i)(api[_-]?key|apikey)\s*[=:]\s*['\"]?[\w\-]+",
        r"(?i)(secret|password|passwd|pwd)\s*[=:]\s*['\"]?[\w\-]+",
        r"(?i)(token|access_token|auth_token)\s*[=:]\s*['\"]?[\w\-]+",
        r"(?i)(aws_secret_access_key|aws_access_key_id)\s*[=:]\s*['\"]?[\w\-]+",
        r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----",
        r"(?i)client_secret\s*[=:]\s*['\"]?[\w\-]+",
        # AWS access key IDs (20 char, starts with AKIA)
        r"AKIA[A-Z0-9]{16}",
        # JWT tokens (base64url encoded header.payload)
        r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}",
        # Slack tokens
        r"xox[bpras]-[A-Za-z0-9\-]{10,}",
    ]

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self.detections: list[PIIDetection] = []
        self.stats = {
            "files_scanned": 0,
            "pii_detected": 0,
            "secrets_detected": 0,
            "routed_to_restricted": 0,
            "blocked": 0,
        }

    def route(self, file_path: str, content: Optional[str] = None) -> dict:
        """
        Determine routing for a file.

        Args:
            file_path: Path or name of the file.
            content: Optional text content for secret scanning.

        Returns:
            Routing decision dict with bucket and reason.
        """
        self.stats["files_scanned"] += 1

        # Check path-based PII patterns
        pii_match = self._check_pii_path(file_path)
        if pii_match:
            detection = PIIDetection(
                file_path=file_path,
                detection_type="pii_path",
                pattern_matched=pii_match,
                action="route_restricted",
            )
            self.detections.append(detection)
            self.stats["pii_detected"] += 1
            self.stats["routed_to_restricted"] += 1
            return {
                "bucket": self.config.RESTRICTED_BUCKET,
                "reason": f"PII path pattern: '{pii_match}'",
                "action": "route_restricted",
                "detection": detection.to_dict(),
            }

        # Check content for secrets
        if content:
            secret_match = self._check_secrets(content)
            if secret_match:
                detection = PIIDetection(
                    file_path=file_path,
                    detection_type="secret_content",
                    pattern_matched=secret_match,
                    action="block",
                )
                self.detections.append(detection)
                self.stats["secrets_detected"] += 1
                self.stats["blocked"] += 1
                return {
                    "bucket": None,  # Blocked - do not load anywhere
                    "reason": f"Secret detected: '{secret_match}'",
                    "action": "block",
                    "detection": detection.to_dict(),
                }

        # Clean file - route to main bucket
        return {
            "bucket": self.config.MAIN_BUCKET,
            "reason": "clean",
            "action": "route_main",
            "detection": None,
        }

    def _check_pii_path(self, file_path: str) -> Optional[str]:
        """Check if file path contains PII indicators (case-insensitive)."""
        path_lower = file_path.lower()
        for pattern in self.config.PII_PATTERNS:
            if pattern.lower() in path_lower:
                return pattern
        return None

    def _check_secrets(self, content: str) -> Optional[str]:
        """Check content for secret patterns."""
        for pattern in self.SECRET_PATTERNS:
            match = re.search(pattern, content)
            if match:
                return pattern.split(r"\s")[0].replace("(?i)", "").replace("(", "").split("|")[0]
        return None

    def get_manifest(self) -> dict:
        """Get PII routing manifest for audit trail."""
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": self.stats,
            "detections": [d.to_dict() for d in self.detections],
        }
