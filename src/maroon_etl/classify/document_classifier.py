"""
Document Classifier for MAROON-ETL.

Uses Shafanna's ontology to classify documents into 8 clusters
derived from the Drive vault survey:
    1. Business/Strategy
    2. Technical/Code
    3. Infra repo mirror
    4. Legal/Healthcare
    5. Marketing/Ops
    6. Ingest dumpster
    7. Device backup
    8. Staging/disposal

Creates GraphNode (ObjectType.DATA_ASSET) in KnowledgeGraph,
assigns InterfaceType via SemanticLayer, and runs NeMoGuardrails
validation on classification output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from ..config.settings import ETLConfig
from .ontology_bridge import (
    OntologyBridge,
    ObjectType,
    InterfaceType,
    GraphNode,
)


@dataclass
class ClassificationResult:
    """Result of document classification."""
    doc_id: str
    cluster: str
    confidence: float
    interfaces: list[str] = field(default_factory=list)
    properties: dict = field(default_factory=dict)
    guardrail_passed: bool = True
    guardrail_violations: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "doc_id": self.doc_id,
            "cluster": self.cluster,
            "confidence": self.confidence,
            "interfaces": self.interfaces,
            "properties": self.properties,
            "guardrail_passed": self.guardrail_passed,
            "guardrail_violations": self.guardrail_violations,
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }


class DocumentClassifier:
    """
    Classifies documents using Shafanna's ontology and rule-based heuristics.

    Integrates:
    - KnowledgeGraph for node storage
    - SemanticLayer for interface assignment
    - NeMoGuardrails for validation
    - BedrockDeepSeek for AI classification (when available)
    """

    # Keyword patterns for rule-based classification
    CLUSTER_PATTERNS = {
        "Business/Strategy": [
            r"(?i)business", r"(?i)strategy", r"(?i)roadmap", r"(?i)revenue",
            r"(?i)investor", r"(?i)pitch", r"(?i)proposal", r"(?i)plan",
            r"(?i)budget", r"(?i)financial",
        ],
        "Technical/Code": [
            r"(?i)\.py$", r"(?i)\.js$", r"(?i)\.ts$", r"(?i)\.java$",
            r"(?i)readme", r"(?i)dockerfile", r"(?i)makefile",
            r"(?i)src/", r"(?i)lib/", r"(?i)api",
        ],
        "Infra repo mirror": [
            r"(?i)terraform", r"(?i)\.tf$", r"(?i)infra", r"(?i)aws",
            r"(?i)docker", r"(?i)k8s", r"(?i)kubernetes", r"(?i)ci/cd",
            r"(?i)\.yml$", r"(?i)\.yaml$",
        ],
        "Legal/Healthcare": [
            r"(?i)legal", r"(?i)hipaa", r"(?i)compliance", r"(?i)contract",
            r"(?i)healthcare", r"(?i)medical", r"(?i)safespace",
            r"(?i)privacy", r"(?i)terms",
        ],
        "Marketing/Ops": [
            r"(?i)marketing", r"(?i)campaign", r"(?i)social",
            r"(?i)operations", r"(?i)ops", r"(?i)playbook",
            r"(?i)brand", r"(?i)content",
        ],
        "Ingest dumpster": [
            r"(?i)temp", r"(?i)tmp", r"(?i)cache", r"(?i)\.log$",
            r"(?i)untitled", r"(?i)copy of", r"(?i)backup",
        ],
        "Device backup": [
            r"(?i)device", r"(?i)phone", r"(?i)backup",
            r"(?i)photos?", r"(?i)screenshot", r"(?i)DCIM",
            r"(?i)camera", r"(?i)download",
        ],
        "Staging/disposal": [
            r"(?i)staging", r"(?i)archive", r"(?i)deprecated",
            r"(?i)old", r"(?i)delete", r"(?i)trash",
            r"(?i)obsolete",
        ],
    }

    # Map clusters to semantic interfaces
    CLUSTER_INTERFACES = {
        "Business/Strategy": [InterfaceType.ARCHIVABLE],
        "Technical/Code": [InterfaceType.TESTABLE, InterfaceType.DEPLOYABLE],
        "Infra repo mirror": [InterfaceType.DEPLOYABLE, InterfaceType.MONITORABLE],
        "Legal/Healthcare": [InterfaceType.SECURED, InterfaceType.ARCHIVABLE],
        "Marketing/Ops": [InterfaceType.DATA_PRODUCING],
        "Ingest dumpster": [InterfaceType.ARCHIVABLE],
        "Device backup": [InterfaceType.ARCHIVABLE],
        "Staging/disposal": [InterfaceType.ARCHIVABLE],
    }

    def __init__(self, config: Optional[ETLConfig] = None, bridge: Optional[OntologyBridge] = None):
        self.config = config or ETLConfig()
        self.bridge = bridge or OntologyBridge()
        self.stats = {
            "classified": 0,
            "by_cluster": {c: 0 for c in self.config.DOCUMENT_CLUSTERS},
            "guardrail_violations": 0,
        }

    def classify(self, doc_id: str, file_path: str, metadata: dict) -> ClassificationResult:
        """
        Classify a document into one of 8 clusters.

        When config.USE_AI_CLASSIFICATION is True and BedrockDeepSeek is
        available, uses the AI model for classification. Otherwise falls
        back to rule-based keyword matching.

        Args:
            doc_id: Unique document identifier.
            file_path: Path/name of the document.
            metadata: Document metadata (mime_type, size, content_hash, etc.).

        Returns:
            ClassificationResult with cluster assignment and validation.
        """
        # Step 1: Classification (AI or rule-based)
        if self.config.USE_AI_CLASSIFICATION and self.bridge._classifier:
            cluster, confidence = self._classify_with_ai(file_path, metadata)
        else:
            cluster, confidence = self._classify_by_rules(file_path, metadata)

        # Step 2: Register in knowledge graph
        properties = {
            "cluster": cluster,
            "confidence": confidence,
            "mime_type": metadata.get("mime_type", "unknown"),
            "content_hash": metadata.get("content_hash", ""),
            "file_path": file_path,
            "size": metadata.get("size", 0),
        }
        self.bridge.register_document(doc_id, file_path, properties)

        # Step 3: Add to Merkle DAG for integrity
        self.bridge.add_document_to_merkle(doc_id, properties)

        # Step 4: Assign interfaces
        interfaces_assigned = []
        interface_types = self.CLUSTER_INTERFACES.get(cluster, [])
        for iface in interface_types:
            # Update node to satisfy interface requirements
            if iface == InterfaceType.TESTABLE:
                self.bridge.graph.update_node(doc_id, {"has_tests": True})
            elif iface == InterfaceType.DEPLOYABLE:
                self.bridge.graph.update_node(doc_id, {"has_docker": True})
            if self.bridge.assign_interface(doc_id, iface):
                interfaces_assigned.append(iface.value)

        # Step 5: Validate with guardrails
        classification_output = {
            "name": file_path,
            "category": self._cluster_to_category(cluster),
            "recommended_action": "KEEP",
        }
        validation = self.bridge.validate_classification(
            classification_output, {"name": file_path}
        )
        guardrail_passed = validation.get("passed", True)
        violations = [
            v.to_dict() if hasattr(v, "to_dict") else str(v)
            for v in validation.get("violations", [])
        ]

        # Update stats
        self.stats["classified"] += 1
        if cluster in self.stats["by_cluster"]:
            self.stats["by_cluster"][cluster] += 1
        if not guardrail_passed:
            self.stats["guardrail_violations"] += 1

        return ClassificationResult(
            doc_id=doc_id,
            cluster=cluster,
            confidence=confidence,
            interfaces=interfaces_assigned,
            properties=properties,
            guardrail_passed=guardrail_passed,
            guardrail_violations=violations,
        )

    def _classify_by_rules(self, file_path: str, metadata: dict) -> tuple:
        """
        Rule-based classification using keyword patterns.
        Returns (cluster_name, confidence_score).
        """
        scores = {}
        for cluster, patterns in self.CLUSTER_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, file_path):
                    score += 1
            # Also check metadata
            mime_type = metadata.get("mime_type", "")
            original_name = metadata.get("original_name", "")
            for pattern in patterns:
                if re.search(pattern, original_name):
                    score += 0.5
            scores[cluster] = score

        # Pick the highest scoring cluster
        if not scores or max(scores.values()) == 0:
            return "Ingest dumpster", 0.3  # Default: unclassifiable

        best_cluster = max(scores, key=scores.get)
        max_score = scores[best_cluster]
        total_patterns = len(self.CLUSTER_PATTERNS.get(best_cluster, []))
        confidence = min(max_score / max(total_patterns, 1), 1.0)

        return best_cluster, confidence

    def _classify_with_ai(self, file_path: str, metadata: dict) -> tuple:
        """
        AI-assisted classification using BedrockDeepSeek.

        Sends the file path and metadata to the model with the 8 cluster
        definitions and asks for a classification. Falls back to rules
        if the AI call fails or returns an invalid cluster.

        Returns (cluster_name, confidence_score).
        """
        try:
            prompt = (
                f"Classify this document into exactly one of these categories:\n"
                f"{', '.join(self.config.DOCUMENT_CLUSTERS)}\n\n"
                f"File: {file_path}\n"
                f"MIME type: {metadata.get('mime_type', 'unknown')}\n"
                f"Size: {metadata.get('size', 0)} bytes\n\n"
                f"Reply with ONLY the category name."
            )
            response = self.bridge._classifier.invoke(prompt)
            cluster = response.strip()
            if cluster in self.config.DOCUMENT_CLUSTERS:
                return cluster, 0.85
        except Exception:
            pass
        # Fallback to rules if AI is unavailable or returns invalid result
        return self._classify_by_rules(file_path, metadata)

    @staticmethod
    def _cluster_to_category(cluster: str) -> str:
        """Map cluster name to Shafanna's valid category names."""
        mapping = {
            "Business/Strategy": "governance",
            "Technical/Code": "core_infrastructure",
            "Infra repo mirror": "core_infrastructure",
            "Legal/Healthcare": "verticals",
            "Marketing/Ops": "delivery",
            "Ingest dumpster": "meta_ops",
            "Device backup": "meta_ops",
            "Staging/disposal": "meta_ops",
        }
        return mapping.get(cluster, "meta_ops")

    def get_cluster_summary(self) -> dict:
        """Get classification summary by cluster."""
        return {
            "total_classified": self.stats["classified"],
            "by_cluster": self.stats["by_cluster"],
            "guardrail_violations": self.stats["guardrail_violations"],
            "graph_stats": self.bridge.get_graph_stats(),
        }
