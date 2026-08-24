"""
Google Drive Extractor for MAROON-ETL.

Pulls files from the Google Drive vault (folder ID: 1I43aPmvEJmUfbeDOYkzLh9gFXdkp_gh_),
respects exclusion list, handles Google Docs export (to markdown), downloads binary files,
and outputs to raw/ zone with metadata JSON sidecar.

Follows Shafanna's gdrive_connector.py pattern.
Authentication: Service account or OAuth2 (OIDC-backed).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config.settings import ETLConfig
from .content_hash import ContentHasher


class GDriveExtractor:
    """
    Extracts files from Google Drive vault into the raw/ zone.
    Handles exclusions, Google Docs export, and metadata sidecar generation.
    """

    # Google Docs MIME types that require export
    EXPORT_TYPES = {
        "application/vnd.google-apps.document": ("text/markdown", ".md"),
        "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
        "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    }

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self._drive_service = None
        self.stats = {
            "files_discovered": 0,
            "files_excluded": 0,
            "files_extracted": 0,
            "bytes_extracted": 0,
            "errors": [],
        }

    @property
    def drive_service(self):
        """Initialize Google Drive API service (lazy)."""
        if self._drive_service is None:
            self._drive_service = self._init_drive()
        return self._drive_service

    def _init_drive(self):
        """
        Initialize Google Drive service using service account or OAuth.

        Raises:
            RuntimeError: If authentication fails (not an ImportError).
                A failed auth must surface as an error, not silently produce
                a successful empty extraction run.
        """
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")
            if sa_path and os.path.exists(sa_path):
                creds = service_account.Credentials.from_service_account_file(
                    sa_path,
                    scopes=["https://www.googleapis.com/auth/drive.readonly"],
                )
            else:
                import google.auth
                creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/drive.readonly"],
                )

            return build("drive", "v3", credentials=creds)
        except ImportError:
            # Google API libraries not installed - optional dependency
            return None
        except Exception as e:
            # Auth failure must not be silent - raise so the pipeline
            # reports an error rather than a misleading success with 0 files
            raise RuntimeError(
                f"Google Drive authentication failed: {e}. "
                "Check GOOGLE_SERVICE_ACCOUNT_KEY or application default credentials."
            ) from e

    def extract(
        self,
        folder_id: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> dict:
        """
        Execute extraction: Google Drive folder -> local raw/ output.

        Args:
            folder_id: Google Drive folder ID. Defaults to config.
            output_dir: Local output directory. Defaults to 'data/raw/'.

        Returns:
            Stats dictionary with extraction results.
        """
        folder_id = folder_id or self.config.GDRIVE_FOLDER_ID
        output_path = Path(output_dir or "data/raw")
        output_path.mkdir(parents=True, exist_ok=True)

        # Phase 1: Discover files
        files = self._discover_files(folder_id)
        self.stats["files_discovered"] = len(files)

        # Phase 2: Filter exclusions
        eligible_files = []
        for file_meta in files:
            if self._should_exclude(file_meta):
                self.stats["files_excluded"] += 1
            else:
                eligible_files.append(file_meta)

        # Phase 3: Download each eligible file
        results = []
        for file_meta in eligible_files:
            try:
                result = self._extract_file(file_meta, output_path)
                if result:
                    results.append(result)
                    self.stats["files_extracted"] += 1
                    self.stats["bytes_extracted"] += result.get("size", 0)
            except Exception as e:
                self.stats["errors"].append({
                    "file": file_meta.get("name", "unknown"),
                    "error": str(e),
                })

        return {
            "stats": self.stats,
            "files": results,
            "output_dir": str(output_path),
        }

    def _discover_files(
        self, folder_id: str, depth: int = 0, max_depth: int = 5
    ) -> list[dict]:
        """Recursively discover all files in the Drive folder."""
        if self.drive_service is None:
            return []

        files = []
        page_token = None

        while True:
            query = f"'{folder_id}' in parents and trashed = false"
            response = self.drive_service.files().list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, parents)",
                pageToken=page_token,
                pageSize=100,
            ).execute()

            for item in response.get("files", []):
                if item["mimeType"] == "application/vnd.google-apps.folder":
                    if depth < max_depth:
                        sub_files = self._discover_files(item["id"], depth + 1)
                        files.extend(sub_files)
                else:
                    item["_folder_depth"] = depth
                    item["_folder_id"] = folder_id
                    files.append(item)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return files

    def _should_exclude(self, file_meta: dict) -> bool:
        """Check if a file should be excluded based on config patterns."""
        name = file_meta.get("name", "")
        size = int(file_meta.get("size", 0))

        # Check exclusion patterns (path-based patterns always apply,
        # binary patterns only apply above size threshold)
        if self.config.is_excluded(name, file_size_bytes=size):
            return True

        return False

    def _extract_file(self, file_meta: dict, output_path: Path) -> Optional[dict]:
        """Extract a single file with metadata sidecar."""
        file_id = file_meta["id"]
        file_name = file_meta["name"]
        mime_type = file_meta.get("mimeType", "application/octet-stream")

        # Download content
        content = self._download_content(file_meta)
        if content is None:
            return None

        # Compute content hash for deduplication
        content_hash = ContentHasher.hash_bytes(content)

        # Determine output filename (may change for Google Docs)
        output_name = file_name
        exported_as = None
        if mime_type in self.EXPORT_TYPES:
            export_mime, ext = self.EXPORT_TYPES[mime_type]
            if not file_name.endswith(ext):
                output_name = file_name + ext
            exported_as = export_mime

        # Write content
        file_out = output_path / output_name
        file_out.write_bytes(content)

        # Write metadata sidecar
        metadata = {
            "source": "google_drive",
            "file_id": file_id,
            "original_name": file_name,
            "output_name": output_name,
            "mime_type": mime_type,
            "exported_as": exported_as,
            "size": len(content),
            "content_hash": content_hash,
            "modified_time": file_meta.get("modifiedTime", ""),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "folder_id": file_meta.get("_folder_id", ""),
            "folder_depth": file_meta.get("_folder_depth", 0),
        }

        sidecar_path = output_path / f"{output_name}.meta.json"
        sidecar_path.write_text(json.dumps(metadata, indent=2))

        return metadata

    def _download_content(self, file_meta: dict) -> Optional[bytes]:
        """Download file content from Google Drive."""
        if self.drive_service is None:
            return None

        file_id = file_meta["id"]
        mime_type = file_meta.get("mimeType", "")

        # Google Docs native formats require export
        if mime_type in self.EXPORT_TYPES:
            export_mime, _ = self.EXPORT_TYPES[mime_type]
            content = self.drive_service.files().export(
                fileId=file_id, mimeType=export_mime
            ).execute()
        else:
            content = self.drive_service.files().get_media(fileId=file_id).execute()

        if isinstance(content, str):
            content = content.encode("utf-8")

        return content
