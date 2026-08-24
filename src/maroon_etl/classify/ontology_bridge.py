"""
Ontology Bridge for MAROON-ETL.

Bridge module that imports from vendor/shafanna and provides a simplified
interface for ETL use. Handles import path setup for the submodule.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

# Setup import path for the vendored Shafanna submodule
_vendor_path = str(Path(__file__).resolve().parents[3] / "vendor" / "shafanna")
if _vendor_path not in sys.path:
    sys.path.insert(0, _vendor_path)

# Import from Shafanna ontology
from src.ontology import (  # noqa: E402
    KnowledgeGraph,
    GraphNode,
    GraphEdge,
    ObjectType,
    LinkType,
    DAG,
    CycleDetectedError,
    MerkleDAG,
    MerkleNode,
    MerkleProof,
    SemanticLayer,
    Interface,
    InterfaceType,
    Action,
    NeMoGuardrails,
    Rail,
    RailType,
    Severity,
    _content_hash,
)

# Import the model (optional - may not have boto3 in all environments)
try:
    from src.models import BedrockDeepSeek
    HAS_DEEPSEEK = True
except ImportError:
    HAS_DEEPSEEK = False
    BedrockDeepSeek = None


class OntologyBridge:
    """
    Simplified interface to Shafanna's ontology for ETL use.
    Wraps KnowledgeGraph, SemanticLayer, MerkleDAG, DAG, and NeMoGuardrails.
    """

    def __init__(self):
        self.graph = KnowledgeGraph()
        self.semantic = SemanticLayer(self.graph)
        self.merkle = MerkleDAG()
        self.dag = DAG()
        self.guardrails = NeMoGuardrails()
        self._classifier = BedrockDeepSeek() if HAS_DEEPSEEK else None

    def register_document(
        self,
        doc_id: str,
        name: str,
        properties: Optional[dict] = None,
    ) -> GraphNode:
        """
        Register a document as a DATA_ASSET in the knowledge graph.

        Args:
            doc_id: Unique document identifier.
            name: Document name.
            properties: Additional properties.

        Returns:
            The created GraphNode.
        """
        props = properties or {}
        node = self.graph.add_node(
            node_id=doc_id,
            object_type=ObjectType.DATA_ASSET,
            name=name,
            properties=props,
        )
        # Auto-assign interfaces
        self.semantic.enrich_node(doc_id, auto_interfaces=True)
        return node

    def add_document_to_merkle(self, doc_id: str, data: dict) -> MerkleNode:
        """Add a document to the Merkle DAG for integrity tracking."""
        return self.merkle.add_node(doc_id, data)

    def add_dependency(self, from_doc: str, to_doc: str) -> None:
        """Track document dependency in the DAG."""
        self.dag.add_edge(from_doc, to_doc)

    def verify_integrity(self) -> dict:
        """Verify Merkle DAG integrity."""
        return self.merkle.verify_integrity()

    def get_build_order(self) -> list:
        """Get processing order from DAG."""
        return self.dag.topological_sort()

    def validate_classification(self, classification: dict, doc_data: dict = None) -> dict:
        """Validate a classification result using guardrails."""
        return self.guardrails.validate_classification(classification, doc_data)

    def assign_interface(self, doc_id: str, interface_type: InterfaceType) -> bool:
        """Assign a semantic interface to a document."""
        return self.semantic.assign_interface(doc_id, interface_type)

    def get_graph_stats(self) -> dict:
        """Get knowledge graph statistics."""
        return {
            "graph": self.graph.stats(),
            "semantic": self.semantic.stats(),
            "merkle_nodes": self.merkle.node_count,
            "merkle_root": self.merkle.root_hash,
            "dag_nodes": self.dag.node_count,
        }

    @staticmethod
    def content_hash(data: Any) -> str:
        """Compute content hash using Shafanna's pattern."""
        return _content_hash(data)
