"""
S3 Lifecycle Manager for MAROON-ETL.

Configures lifecycle rules for the data lake:
- raw/ zone -> Glacier after 90 days
- Future: Athena integration pattern documentation

Budget constraint: UNDER $0.10/month.
"""

from __future__ import annotations

from typing import Optional

try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

from ..config.settings import ETLConfig


class LifecycleManager:
    """
    Manages S3 lifecycle policies for cost optimization.
    Raw zone transitions to Glacier after 90 days.
    """

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self._client = None

    @property
    def client(self):
        """Lazy-initialize S3 client."""
        if self._client is None:
            if not HAS_BOTO3:
                raise RuntimeError("boto3 not installed")
            self._client = boto3.client(
                "s3",
                config=Config(region_name=self.config.AWS_REGION),
            )
        return self._client

    def get_lifecycle_rules(self) -> list[dict]:
        """
        Get the lifecycle rules for the main data lake bucket.

        Returns:
            List of lifecycle rule configurations.
        """
        return [
            {
                "ID": "raw-to-glacier-90d",
                "Status": "Enabled",
                "Filter": {"Prefix": self.config.RAW_PREFIX},
                "Transitions": [
                    {
                        "Days": self.config.RAW_GLACIER_TRANSITION_DAYS,
                        "StorageClass": "GLACIER",
                    }
                ],
                "NoncurrentVersionTransitions": [
                    {
                        "NoncurrentDays": 30,
                        "StorageClass": "GLACIER",
                    }
                ],
            },
            {
                "ID": "manifests-ia-30d",
                "Status": "Enabled",
                "Filter": {"Prefix": self.config.MANIFESTS_PREFIX},
                "Transitions": [
                    {
                        "Days": 30,
                        "StorageClass": "STANDARD_IA",
                    }
                ],
            },
        ]

    def apply_lifecycle(self) -> dict:
        """
        Apply lifecycle configuration to the main bucket.

        Returns:
            Result dict indicating success or failure.
        """
        rules = self.get_lifecycle_rules()
        try:
            self.client.put_bucket_lifecycle_configuration(
                Bucket=self.config.MAIN_BUCKET,
                LifecycleConfiguration={"Rules": rules},
            )
            return {
                "success": True,
                "bucket": self.config.MAIN_BUCKET,
                "rules_applied": len(rules),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_athena_pattern(self) -> dict:
        """
        Document the Athena integration pattern (future state).
        Not built now - this is documentation only.
        """
        return {
            "status": "planned",
            "description": "Athena queries over curated/ zone using Glue Catalog",
            "database": "maroon_datalake",
            "tables": {
                "curated_documents": {
                    "location": f"s3://{self.config.MAIN_BUCKET}/{self.config.CURATED_PREFIX}",
                    "format": "JSON",
                    "partition_keys": ["cluster", "year", "month"],
                },
                "manifests": {
                    "location": f"s3://{self.config.MAIN_BUCKET}/{self.config.MANIFESTS_PREFIX}",
                    "format": "JSON",
                },
            },
            "estimated_cost": "< $0.01/query (5MB scanned per typical query)",
            "notes": "Athena is pay-per-query. Fits $0.10/month budget if queries are rare.",
        }
