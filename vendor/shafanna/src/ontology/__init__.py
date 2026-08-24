"""
Shafanna Ontology - vendored for MAROON-ETL integration.

Provides: KnowledgeGraph, DAG, MerkleDAG, SemanticLayer, NeMoGuardrails.
"""

from .knowledge_graph import (
    KnowledgeGraph, GraphNode, GraphEdge,
    ObjectType, LinkType, PropertyType, PropertySchema,
)
from .dag import DAG, CycleDetectedError
from .merkle import MerkleDAG, MerkleNode, MerkleProof, _content_hash
from .semantic import SemanticLayer, Interface, Action, InterfaceType
from .guardrails import NeMoGuardrails, Rail, RailType, Severity

__all__ = [
    # Knowledge Graph
    "KnowledgeGraph",
    "GraphNode",
    "GraphEdge",
    "ObjectType",
    "LinkType",
    "PropertyType",
    "PropertySchema",
    # DAG
    "DAG",
    "CycleDetectedError",
    # Merkle
    "MerkleDAG",
    "MerkleNode",
    "MerkleProof",
    "_content_hash",
    # Semantic
    "SemanticLayer",
    "Interface",
    "Action",
    "InterfaceType",
    # Guardrails
    "NeMoGuardrails",
    "Rail",
    "RailType",
    "Severity",
]
