"""
Audit Trail for MAROON-ETL.

Records every pipeline operation with timestamps, input/output hashes,
and classification results. Stored as JSON in _manifests/audit/ prefix.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass
class AuditEntry:
    """A single audit trail entry."""
    operation: str  # extract, transform, classify, load, validate
    doc_id: str
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    classification: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "operation": self.operation,
            "doc_id": self.doc_id,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "classification": self.classification,
            "metadata": self.metadata,
            "success": self.success,
            "error": self.error,
            "timestamp": self.timestamp,
        }


class AuditTrail:
    """
    Records all pipeline operations for compliance and debugging.
    Provides complete audit history for every document processed.
    """

    def __init__(self):
        self._entries: list[AuditEntry] = []
        self._by_doc: dict[str, list[AuditEntry]] = {}

    def record(
        self,
        operation: str,
        doc_id: str,
        input_hash: Optional[str] = None,
        output_hash: Optional[str] = None,
        classification: Optional[str] = None,
        metadata: Optional[dict] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> AuditEntry:
        """
        Record an audit entry.

        Args:
            operation: Type of operation (extract, transform, classify, load, validate).
            doc_id: Document identifier.
            input_hash: Hash of input data.
            output_hash: Hash of output data.
            classification: Classification result.
            metadata: Additional metadata.
            success: Whether operation succeeded.
            error: Error message if failed.

        Returns:
            The recorded AuditEntry.
        """
        entry = AuditEntry(
            operation=operation,
            doc_id=doc_id,
            input_hash=input_hash,
            output_hash=output_hash,
            classification=classification,
            metadata=metadata or {},
            success=success,
            error=error,
        )
        self._entries.append(entry)
        if doc_id not in self._by_doc:
            self._by_doc[doc_id] = []
        self._by_doc[doc_id].append(entry)
        return entry

    def get_entries(self, doc_id: Optional[str] = None) -> list[AuditEntry]:
        """Get audit entries, optionally filtered by doc_id."""
        if doc_id:
            return self._by_doc.get(doc_id, [])
        return list(self._entries)

    def get_failures(self) -> list[AuditEntry]:
        """Get all failed operations."""
        return [e for e in self._entries if not e.success]

    @property
    def entry_count(self) -> int:
        """Total number of audit entries."""
        return len(self._entries)

    @property
    def failure_count(self) -> int:
        """Number of failed operations."""
        return sum(1 for e in self._entries if not e.success)

    def generate_manifest(self) -> dict:
        """
        Generate audit manifest for storage in _manifests/audit/.

        Returns:
            Complete audit trail as a serializable dict.
        """
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_entries": self.entry_count,
            "failures": self.failure_count,
            "operations_summary": self._summarize_operations(),
            "entries": [e.to_dict() for e in self._entries],
        }

    def _summarize_operations(self) -> dict:
        """Summarize operations by type."""
        summary: dict[str, dict] = {}
        for entry in self._entries:
            if entry.operation not in summary:
                summary[entry.operation] = {"total": 0, "success": 0, "failed": 0}
            summary[entry.operation]["total"] += 1
            if entry.success:
                summary[entry.operation]["success"] += 1
            else:
                summary[entry.operation]["failed"] += 1
        return summary

    def save_local(self, output_dir: str = "data/_manifests/audit") -> str:
        """
        Save audit trail to local JSON file.

        Args:
            output_dir: Directory to save audit file.

        Returns:
            Path to the saved file.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"audit_{timestamp}.json"
        filepath = output_path / filename

        manifest = self.generate_manifest()
        filepath.write_text(json.dumps(manifest, indent=2))
        return str(filepath)
