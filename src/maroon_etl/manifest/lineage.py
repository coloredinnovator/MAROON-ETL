"""
Lineage Tracker for MAROON-ETL.

Uses Shafanna's DAG for dependency tracking and MerkleDAG for integrity
verification. Each document gets:
    - source_hash: hash at extraction
    - transform_hash: hash after transformation
    - load_hash: hash at load time

Manifests are written to _manifests/ prefix in S3.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..classify.ontology_bridge import (
    DAG,
    CycleDetectedError,
    MerkleDAG,
    MerkleNode,
    MerkleProof,
    _content_hash,
)


@dataclass
class DocumentLineage:
    """Complete lineage record for a single document."""
    doc_id: str
    source_hash: str
    transform_hash: Optional[str] = None
    load_hash: Optional[str] = None
    classification: Optional[str] = None
    source_path: str = ""
    staged_path: str = ""
    curated_path: str = ""
    s3_uri: str = ""
    pipeline_stage: str = "extracted"  # extracted -> transformed -> loaded
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        """Serialize lineage record."""
        return {
            "doc_id": self.doc_id,
            "source_hash": self.source_hash,
            "transform_hash": self.transform_hash,
            "load_hash": self.load_hash,
            "classification": self.classification,
            "source_path": self.source_path,
            "staged_path": self.staged_path,
            "curated_path": self.curated_path,
            "s3_uri": self.s3_uri,
            "pipeline_stage": self.pipeline_stage,
            "created_at": self.created_at,
        }


class LineageTracker:
    """
    Tracks document lineage through the ETL pipeline.
    Uses DAG for dependency ordering and MerkleDAG for integrity.
    """

    def __init__(self):
        self.dag = DAG()
        self.merkle = MerkleDAG()
        self._lineage: dict[str, DocumentLineage] = {}
        self._root_id = "pipeline_root"
        # Initialize root node in Merkle DAG
        self.merkle.add_node(self._root_id, {"type": "pipeline_root", "version": "0.1.0"})

    def register_extraction(self, doc_id: str, source_hash: str, source_path: str) -> DocumentLineage:
        """
        Register a document extraction event.

        Args:
            doc_id: Unique document identifier.
            source_hash: SHA-256 hash of extracted content.
            source_path: Source path/name of the document.

        Returns:
            DocumentLineage record.
        """
        lineage = DocumentLineage(
            doc_id=doc_id,
            source_hash=source_hash,
            source_path=source_path,
            pipeline_stage="extracted",
        )
        self._lineage[doc_id] = lineage

        # Add to DAG (depends on pipeline root)
        self.dag.add_node(doc_id)
        try:
            self.dag.add_edge(doc_id, self._root_id)
        except CycleDetectedError:
            pass

        # Add to Merkle DAG
        self.merkle.add_node(
            doc_id,
            {"source_hash": source_hash, "stage": "extracted"},
            parent_id=self._root_id,
        )

        return lineage

    def register_transform(self, doc_id: str, transform_hash: str, staged_path: str = "") -> Optional[DocumentLineage]:
        """
        Register a document transformation event.

        Args:
            doc_id: Document identifier.
            transform_hash: SHA-256 hash after transformation.
            staged_path: Path in staged zone.

        Returns:
            Updated DocumentLineage, or None if not found.
        """
        lineage = self._lineage.get(doc_id)
        if not lineage:
            return None

        lineage.transform_hash = transform_hash
        lineage.staged_path = staged_path
        lineage.pipeline_stage = "transformed"

        # Update Merkle DAG
        self.merkle.update_node(
            doc_id,
            {"source_hash": lineage.source_hash, "transform_hash": transform_hash, "stage": "transformed"},
        )

        return lineage

    def register_load(
        self, doc_id: str, load_hash: str, s3_uri: str = "", classification: str = ""
    ) -> Optional[DocumentLineage]:
        """
        Register a document load event.

        Args:
            doc_id: Document identifier.
            load_hash: SHA-256 hash at load time.
            s3_uri: S3 URI where document was loaded.
            classification: Cluster classification.

        Returns:
            Updated DocumentLineage, or None if not found.
        """
        lineage = self._lineage.get(doc_id)
        if not lineage:
            return None

        lineage.load_hash = load_hash
        lineage.s3_uri = s3_uri
        lineage.classification = classification
        lineage.pipeline_stage = "loaded"

        # Update Merkle DAG
        self.merkle.update_node(
            doc_id,
            {
                "source_hash": lineage.source_hash,
                "transform_hash": lineage.transform_hash,
                "load_hash": load_hash,
                "stage": "loaded",
            },
        )

        return lineage

    def add_dependency(self, doc_id: str, depends_on: str) -> bool:
        """Add a dependency between documents."""
        try:
            self.dag.add_edge(doc_id, depends_on)
            return True
        except CycleDetectedError:
            return False

    def verify_integrity(self) -> dict:
        """Verify the integrity of all tracked documents."""
        return self.merkle.verify_integrity()

    def get_proof(self, doc_id: str) -> Optional[MerkleProof]:
        """Get a Merkle proof for a document."""
        return self.merkle.generate_proof(doc_id)

    def get_lineage(self, doc_id: str) -> Optional[DocumentLineage]:
        """Get lineage record for a document."""
        return self._lineage.get(doc_id)

    def get_processing_order(self) -> list[str]:
        """Get topologically sorted processing order."""
        return self.dag.topological_sort()

    def generate_manifest(self) -> dict:
        """
        Generate a complete lineage manifest.
        Written to _manifests/ prefix.
        """
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_version": "0.1.0",
            "merkle_root_hash": self.merkle.root_hash,
            "integrity": self.merkle.verify_integrity(),
            "document_count": len(self._lineage),
            "documents": {
                doc_id: lineage.to_dict()
                for doc_id, lineage in self._lineage.items()
            },
            "dag_stats": {
                "nodes": self.dag.node_count,
                "roots": self.dag.roots(),
                "leaves": self.dag.leaves(),
            },
        }
