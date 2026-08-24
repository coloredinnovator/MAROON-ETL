"""
S3 Loader for MAROON-ETL.

Loads staged/curated data to S3 with SSE-S3 encryption, content-type
detection, and metadata tagging with ontology classification.
Supports both main and restricted buckets.
Follows Shafanna's s3_loader.py patterns.
"""

from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import boto3
    from botocore.config import Config
    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False

from ..config.settings import ETLConfig


class S3Loader:
    """
    Loads data to S3 data lake with proper encryption and metadata.
    Supports routing to main or restricted bucket based on classification.
    """

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self._client = None
        self.stats = {
            "files_loaded": 0,
            "bytes_loaded": 0,
            "main_bucket_loads": 0,
            "restricted_bucket_loads": 0,
            "errors": [],
        }

    @property
    def client(self):
        """Lazy-initialize S3 client."""
        if self._client is None:
            if not HAS_BOTO3:
                raise RuntimeError("boto3 not installed. Run: pip install boto3")
            self._client = boto3.client(
                "s3",
                config=Config(region_name=self.config.AWS_REGION),
            )
        return self._client

    def load_file(
        self,
        local_path: str,
        s3_key: str,
        bucket: Optional[str] = None,
        metadata: Optional[dict] = None,
        classification: Optional[dict] = None,
    ) -> dict:
        """
        Load a file to S3 with encryption and metadata.

        Args:
            local_path: Path to the local file.
            s3_key: S3 object key.
            bucket: Target bucket (defaults to main).
            metadata: Additional S3 metadata.
            classification: Ontology classification to tag.

        Returns:
            Load result dict with S3 URI and metadata.
        """
        bucket = bucket or self.config.MAIN_BUCKET
        content_type = self._detect_content_type(local_path)

        # Build S3 metadata
        s3_metadata = {
            "etl-pipeline": "maroon-etl",
            "loaded-at": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            for k, v in metadata.items():
                s3_metadata[str(k)] = str(v)
        if classification:
            s3_metadata["cluster"] = str(classification.get("cluster", ""))
            s3_metadata["confidence"] = str(classification.get("confidence", ""))
            s3_metadata["content-hash"] = str(classification.get("content_hash", ""))

        file_path = Path(local_path)
        file_size = file_path.stat().st_size if file_path.exists() else 0

        try:
            with open(local_path, "rb") as f:
                self.client.put_object(
                    Bucket=bucket,
                    Key=s3_key,
                    Body=f,
                    ContentType=content_type,
                    ServerSideEncryption=self.config.ENCRYPTION_METHOD,
                    Metadata=s3_metadata,
                )

            self.stats["files_loaded"] += 1
            self.stats["bytes_loaded"] += file_size
            if bucket == self.config.RESTRICTED_BUCKET:
                self.stats["restricted_bucket_loads"] += 1
            else:
                self.stats["main_bucket_loads"] += 1

            return {
                "success": True,
                "s3_uri": f"s3://{bucket}/{s3_key}",
                "bucket": bucket,
                "key": s3_key,
                "size": file_size,
                "content_type": content_type,
                "metadata": s3_metadata,
            }

        except Exception as e:
            error = {"file": local_path, "key": s3_key, "error": str(e)}
            self.stats["errors"].append(error)
            return {
                "success": False,
                "error": str(e),
                "file": local_path,
            }

    def load_bytes(
        self,
        data: bytes,
        s3_key: str,
        bucket: Optional[str] = None,
        content_type: str = "application/octet-stream",
        metadata: Optional[dict] = None,
    ) -> dict:
        """
        Load raw bytes to S3.

        Args:
            data: Bytes to upload.
            s3_key: S3 object key.
            bucket: Target bucket.
            content_type: MIME type.
            metadata: S3 metadata tags.

        Returns:
            Load result dict.
        """
        bucket = bucket or self.config.MAIN_BUCKET

        s3_metadata = {
            "etl-pipeline": "maroon-etl",
            "loaded-at": datetime.now(timezone.utc).isoformat(),
        }
        if metadata:
            for k, v in metadata.items():
                s3_metadata[str(k)] = str(v)

        try:
            self.client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption=self.config.ENCRYPTION_METHOD,
                Metadata=s3_metadata,
            )

            self.stats["files_loaded"] += 1
            self.stats["bytes_loaded"] += len(data)
            if bucket == self.config.RESTRICTED_BUCKET:
                self.stats["restricted_bucket_loads"] += 1
            else:
                self.stats["main_bucket_loads"] += 1

            return {
                "success": True,
                "s3_uri": f"s3://{bucket}/{s3_key}",
                "bucket": bucket,
                "key": s3_key,
                "size": len(data),
            }

        except Exception as e:
            self.stats["errors"].append({"key": s3_key, "error": str(e)})
            return {"success": False, "error": str(e)}

    def load_json(
        self,
        data: dict,
        s3_key: str,
        bucket: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """Load JSON data to S3."""
        json_bytes = json.dumps(data, indent=2, default=str).encode("utf-8")
        return self.load_bytes(
            json_bytes, s3_key, bucket, "application/json", metadata
        )

    def _detect_content_type(self, file_path: str) -> str:
        """Detect MIME type from file extension."""
        content_type, _ = mimetypes.guess_type(file_path)
        if content_type:
            return content_type
        # Fallback mappings
        ext = Path(file_path).suffix.lower()
        mapping = {
            ".md": "text/markdown",
            ".py": "text/x-python",
            ".yaml": "application/x-yaml",
            ".yml": "application/x-yaml",
            ".tf": "text/plain",
            ".json": "application/json",
        }
        return mapping.get(ext, "application/octet-stream")
