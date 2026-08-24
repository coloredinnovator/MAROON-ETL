"""
Format Converter for MAROON-ETL.

Converts documents to canonical formats for the staged zone:
- Google Doc -> markdown (via export)
- PDF -> text (basic extraction)
- .docx -> text (basic extraction)
- Filters binary noise (Chromium/Electron junk > 10MB)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config.settings import ETLConfig
from ..extract.content_hash import ContentHasher


class FormatConverter:
    """
    Converts documents to normalized formats for the staged zone.
    Binary noise is filtered. Text-based docs are standardized.
    """

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self.stats = {
            "converted": 0,
            "passed_through": 0,
            "filtered_binary": 0,
            "errors": [],
        }

    def convert(self, file_path: str, metadata: dict, output_dir: str) -> Optional[dict]:
        """
        Convert a file to its canonical format.

        Args:
            file_path: Path to the source file.
            metadata: File metadata (mime_type, size, etc.).
            output_dir: Directory to write converted output.

        Returns:
            Updated metadata dict with conversion info, or None if filtered.
        """
        mime_type = metadata.get("mime_type", "application/octet-stream")
        size = metadata.get("size", 0)
        file_name = metadata.get("original_name", Path(file_path).name)

        # Filter binary noise
        if self._is_binary_noise(file_name, size):
            self.stats["filtered_binary"] += 1
            return None

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Route by mime type
        if mime_type == "application/pdf":
            return self._convert_pdf(file_path, file_name, metadata, output_path)
        elif mime_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ):
            return self._convert_docx(file_path, file_name, metadata, output_path)
        elif mime_type in ("text/markdown", "text/plain", "text/x-python", "application/json"):
            return self._pass_through(file_path, file_name, metadata, output_path)
        else:
            return self._pass_through(file_path, file_name, metadata, output_path)

    def _is_binary_noise(self, file_name: str, size: int) -> bool:
        """Check if a file is Chromium/Electron binary noise."""
        name_lower = file_name.lower()
        size_mb = size / (1024 * 1024) if size > 0 else 0

        for pattern in self.config.BINARY_EXCLUSION_PATTERNS:
            if pattern.lower() in name_lower:
                if size_mb > self.config.BINARY_SIZE_LIMIT_MB:
                    return True
        return False

    def _convert_pdf(
        self, file_path: str, file_name: str, metadata: dict, output_path: Path
    ) -> dict:
        """Basic PDF text extraction."""
        text_content = ""
        try:
            # Basic PDF text extraction (no heavy dependencies)
            with open(file_path, "rb") as f:
                raw = f.read()
            # Simple heuristic: extract ASCII-range text between stream markers
            text_content = self._extract_text_from_pdf_bytes(raw)
        except Exception as e:
            self.stats["errors"].append({"file": file_name, "error": str(e)})
            text_content = f"[PDF text extraction failed: {file_name}]"

        output_name = Path(file_name).stem + ".txt"
        out_file = output_path / output_name
        out_file.write_text(text_content, encoding="utf-8")

        self.stats["converted"] += 1
        return {
            **metadata,
            "converted_from": "pdf",
            "converted_to": "text",
            "output_file": str(out_file),
            "output_hash": ContentHasher.hash_string(text_content),
            "converted_at": datetime.now(timezone.utc).isoformat(),
        }

    def _convert_docx(
        self, file_path: str, file_name: str, metadata: dict, output_path: Path
    ) -> dict:
        """Basic .docx text extraction (reads XML from zip)."""
        text_content = ""
        try:
            import zipfile
            import xml.etree.ElementTree as ET

            with zipfile.ZipFile(file_path) as zf:
                if "word/document.xml" in zf.namelist():
                    with zf.open("word/document.xml") as doc_xml:
                        tree = ET.parse(doc_xml)
                        root = tree.getroot()
                        # Extract all text nodes
                        ns = {
                            "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                        }
                        paragraphs = root.findall(".//w:p", ns)
                        lines = []
                        for para in paragraphs:
                            texts = para.findall(".//w:t", ns)
                            line = "".join(t.text or "" for t in texts)
                            if line:
                                lines.append(line)
                        text_content = "\n".join(lines)
        except Exception as e:
            self.stats["errors"].append({"file": file_name, "error": str(e)})
            text_content = f"[DOCX text extraction failed: {file_name}]"

        output_name = Path(file_name).stem + ".txt"
        out_file = output_path / output_name
        out_file.write_text(text_content, encoding="utf-8")

        self.stats["converted"] += 1
        return {
            **metadata,
            "converted_from": "docx",
            "converted_to": "text",
            "output_file": str(out_file),
            "output_hash": ContentHasher.hash_string(text_content),
            "converted_at": datetime.now(timezone.utc).isoformat(),
        }

    def _pass_through(
        self, file_path: str, file_name: str, metadata: dict, output_path: Path
    ) -> dict:
        """Pass through text-based files without conversion."""
        src = Path(file_path)
        dst = output_path / file_name

        if src.exists():
            content = src.read_bytes()
            dst.write_bytes(content)
            output_hash = ContentHasher.hash_bytes(content)
        else:
            output_hash = metadata.get("content_hash", "")

        self.stats["passed_through"] += 1
        return {
            **metadata,
            "converted_from": None,
            "converted_to": None,
            "output_file": str(dst),
            "output_hash": output_hash,
            "converted_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _extract_text_from_pdf_bytes(raw: bytes) -> str:
        """
        Basic PDF text extraction without external libraries.
        Extracts text between BT/ET markers (very basic, covers simple PDFs).
        """
        text_parts = []
        try:
            # Look for text objects in the PDF
            content = raw.decode("latin-1", errors="ignore")
            # Find text between parentheses in text objects
            import re
            # Match text strings in PDF content streams
            matches = re.findall(r"\(([^)]+)\)", content)
            for match in matches:
                # Filter out binary garbage
                printable = "".join(
                    c for c in match if c.isprintable() or c in ("\n", "\r", "\t")
                )
                if len(printable) > 3:
                    text_parts.append(printable)
        except Exception:
            pass

        return "\n".join(text_parts) if text_parts else "[No extractable text]"
