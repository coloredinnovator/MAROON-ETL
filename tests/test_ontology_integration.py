"""
Full integration tests for Shafanna ontology components in MAROON-ETL.
Tests: KnowledgeGraph, GraphEdge, MerkleDAG integrity, DAG cycle detection,
SemanticLayer, NeMoGuardrails, and OntologyBridge end-to-end.
"""

import sys
from pathlib import Path

import pytest

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "vendor" / "shafanna"))


class TestKnowledgeGraphDataAssets:
    """Test KnowledgeGraph stores and retrieves DATA_ASSET nodes."""

    def test_add_data_asset_node(self):
        """Can create a DATA_ASSET node and retrieve it."""
        from maroon_etl.classify.ontology_bridge import KnowledgeGraph, ObjectType
        graph = KnowledgeGraph()
        node = graph.add_node(
            "doc_001", ObjectType.DATA_ASSET, "business-plan.md",
            {"cluster": "Business/Strategy", "size": 4096}
        )
        assert node.node_id == "doc_001"
        assert node.object_type == ObjectType.DATA_ASSET
        assert node.name == "business-plan.md"
        assert node.properties["cluster"] == "Business/Strategy"

    def test_retrieve_node_by_id(self):
        """Stored node can be looked up by ID."""
        from maroon_etl.classify.ontology_bridge import KnowledgeGraph, ObjectType
        graph = KnowledgeGraph()
        graph.add_node("doc_alpha", ObjectType.DATA_ASSET, "alpha.pdf")
        retrieved = graph.get_node("doc_alpha")
        assert retrieved is not None
        assert retrieved.name == "alpha.pdf"

    def test_query_by_type(self):
        """Can query all nodes of type DATA_ASSET."""
        from maroon_etl.classify.ontology_bridge import KnowledgeGraph, ObjectType
        graph = KnowledgeGraph()
        graph.add_node("d1", ObjectType.DATA_ASSET, "doc1.md")
        graph.add_node("d2", ObjectType.DATA_ASSET, "doc2.pdf")
        graph.add_node("r1", ObjectType.REPO, "my-repo")

        assets = graph.query_by_type(ObjectType.DATA_ASSET)
        assert len(assets) == 2
        repos = graph.query_by_type(ObjectType.REPO)
        assert len(repos) == 1


class TestGraphEdgeRelationships:
    """Test GraphEdge relationships between documents."""

    def test_create_edge_between_nodes(self):
        """Can create directed edges between nodes."""
        from maroon_etl.classify.ontology_bridge import (
            KnowledgeGraph, ObjectType, LinkType
        )
        graph = KnowledgeGraph()
        graph.add_node("doc_a", ObjectType.DATA_ASSET, "source.md")
        graph.add_node("doc_b", ObjectType.DATA_ASSET, "derived.md")

        edge = graph.add_edge("doc_a", "doc_b", LinkType.PRODUCES)
        assert edge is not None
        assert edge.source_id == "doc_a"
        assert edge.target_id == "doc_b"
        assert edge.link_type == LinkType.PRODUCES

    def test_get_edges_for_node(self):
        """Can retrieve edges connected to a specific node."""
        from maroon_etl.classify.ontology_bridge import (
            KnowledgeGraph, ObjectType, LinkType
        )
        graph = KnowledgeGraph()
        graph.add_node("parent", ObjectType.DATA_ASSET, "parent.md")
        graph.add_node("child1", ObjectType.DATA_ASSET, "child1.md")
        graph.add_node("child2", ObjectType.DATA_ASSET, "child2.md")

        graph.add_edge("parent", "child1", LinkType.PRODUCES)
        graph.add_edge("parent", "child2", LinkType.PRODUCES)

        edges = graph.get_edges("parent", direction="out")
        assert len(edges) == 2

    def test_duplicate_of_relationship(self):
        """DUPLICATE_OF link type can connect duplicate documents."""
        from maroon_etl.classify.ontology_bridge import (
            KnowledgeGraph, ObjectType, LinkType
        )
        graph = KnowledgeGraph()
        graph.add_node("original", ObjectType.DATA_ASSET, "report.md")
        graph.add_node("copy", ObjectType.DATA_ASSET, "report-copy.md")

        edge = graph.add_edge("copy", "original", LinkType.DUPLICATE_OF)
        assert edge.link_type == LinkType.DUPLICATE_OF


class TestMerkleDAGIntegrity:
    """Test MerkleDAG integrity verification."""

    def test_add_node_generates_hash(self):
        """Adding a node produces a valid content hash."""
        from maroon_etl.classify.ontology_bridge import MerkleDAG
        merkle = MerkleDAG()
        node = merkle.add_node("doc1", {"content": "hello", "size": 5})
        assert node.content_hash is not None
        assert len(node.content_hash) == 64

    def test_modify_data_changes_hash(self):
        """Updating node data changes the content hash."""
        from maroon_etl.classify.ontology_bridge import MerkleDAG
        merkle = MerkleDAG()
        node = merkle.add_node("doc1", {"content": "original"})
        original_hash = node.content_hash

        updated = merkle.update_node("doc1", {"content": "modified"})
        assert updated.content_hash != original_hash

    def test_integrity_passes_on_clean_dag(self):
        """Integrity check passes when no data has been tampered with."""
        from maroon_etl.classify.ontology_bridge import MerkleDAG
        merkle = MerkleDAG()
        merkle.add_node("root", {"type": "pipeline"})
        merkle.add_node("child1", {"file": "a.md"}, parent_id="root")
        merkle.add_node("child2", {"file": "b.md"}, parent_id="root")

        result = merkle.verify_integrity()
        assert result["valid"] is True
        assert result["issues"] == []

    def test_root_hash_changes_when_child_modified(self):
        """Modifying a child propagates hash changes to root."""
        from maroon_etl.classify.ontology_bridge import MerkleDAG
        merkle = MerkleDAG()
        merkle.add_node("root", {"type": "pipeline"})
        merkle.add_node("child", {"data": "original"}, parent_id="root")
        root_hash_before = merkle.root_hash

        merkle.update_node("child", {"data": "changed"})
        root_hash_after = merkle.root_hash

        assert root_hash_before != root_hash_after

    def test_generate_proof(self):
        """Can generate a Merkle proof for a node."""
        from maroon_etl.classify.ontology_bridge import MerkleDAG
        merkle = MerkleDAG()
        merkle.add_node("root", {"type": "root"})
        merkle.add_node("leaf", {"type": "leaf"}, parent_id="root")

        proof = merkle.generate_proof("leaf")
        assert proof is not None
        assert proof.node_id == "leaf"
        assert proof.verified is True
        assert len(proof.path_hashes) >= 1


class TestDAGCycleDetection:
    """Test DAG cycle detection when adding circular references."""

    def test_simple_cycle_raises(self):
        """Adding A->B->A raises CycleDetectedError."""
        from maroon_etl.classify.ontology_bridge import DAG, CycleDetectedError
        dag = DAG()
        dag.add_edge("A", "B")
        with pytest.raises(CycleDetectedError):
            dag.add_edge("B", "A")

    def test_indirect_cycle_raises(self):
        """Adding A->B->C->A raises CycleDetectedError."""
        from maroon_etl.classify.ontology_bridge import DAG, CycleDetectedError
        dag = DAG()
        dag.add_edge("A", "B")
        dag.add_edge("B", "C")
        with pytest.raises(CycleDetectedError):
            dag.add_edge("C", "A")

    def test_self_loop_raises(self):
        """Adding A->A raises CycleDetectedError."""
        from maroon_etl.classify.ontology_bridge import DAG, CycleDetectedError
        dag = DAG()
        with pytest.raises(CycleDetectedError):
            dag.add_edge("X", "X")

    def test_valid_dag_no_cycles(self):
        """A valid DAG can be topologically sorted without error."""
        from maroon_etl.classify.ontology_bridge import DAG
        dag = DAG()
        dag.add_edge("extract", "root")
        dag.add_edge("transform", "extract")
        dag.add_edge("load", "transform")

        order = dag.topological_sort()
        assert order.index("root") < order.index("extract")
        assert order.index("extract") < order.index("transform")
        assert order.index("transform") < order.index("load")


class TestSemanticLayerInterfaces:
    """Test SemanticLayer interface assignment."""

    def test_assign_data_producing_interface(self):
        """DATA_PRODUCING interface can be assigned to any node."""
        from maroon_etl.classify.ontology_bridge import (
            KnowledgeGraph, ObjectType, SemanticLayer, InterfaceType
        )
        graph = KnowledgeGraph()
        graph.add_node("asset1", ObjectType.DATA_ASSET, "dataset.csv", {})
        semantic = SemanticLayer(graph)

        # DATA_PRODUCING has no required properties
        result = semantic.assign_interface("asset1", InterfaceType.DATA_PRODUCING)
        assert result is True

    def test_interface_requires_properties(self):
        """DEPLOYABLE interface requires 'has_docker' property."""
        from maroon_etl.classify.ontology_bridge import (
            KnowledgeGraph, ObjectType, SemanticLayer, InterfaceType
        )
        graph = KnowledgeGraph()
        # Node without has_docker property
        graph.add_node("svc1", ObjectType.SERVICE, "my-service", {})
        semantic = SemanticLayer(graph)

        # Should fail - missing required property
        result = semantic.assign_interface("svc1", InterfaceType.DEPLOYABLE)
        assert result is False

        # Add the required property and try again
        graph.update_node("svc1", {"has_docker": True})
        result = semantic.assign_interface("svc1", InterfaceType.DEPLOYABLE)
        assert result is True

    def test_enrich_node_auto_assigns(self):
        """enrich_node auto-assigns applicable interfaces."""
        from maroon_etl.classify.ontology_bridge import (
            KnowledgeGraph, ObjectType, SemanticLayer, InterfaceType
        )
        graph = KnowledgeGraph()
        graph.add_node("app", ObjectType.REPO, "my-app", {"has_docker": True, "has_tests": True})
        semantic = SemanticLayer(graph)

        semantic.enrich_node("app", auto_interfaces=True)
        interfaces = semantic.get_interfaces("app")
        assert InterfaceType.DEPLOYABLE in interfaces
        assert InterfaceType.TESTABLE in interfaces


class TestNeMoGuardrailsValidation:
    """Test NeMoGuardrails validate_classification."""

    def test_valid_classification_passes(self):
        """A valid classification output passes guardrails."""
        from maroon_etl.classify.ontology_bridge import NeMoGuardrails
        guardrails = NeMoGuardrails()
        classification = {
            "category": "core_infrastructure",
            "recommended_action": "KEEP",
            "name": "my-repo",
        }
        result = guardrails.validate_classification(
            classification, {"name": "my-repo"}
        )
        assert result["passed"] is True

    def test_invalid_category_blocked(self):
        """Invalid category triggers schema rail block."""
        from maroon_etl.classify.ontology_bridge import NeMoGuardrails
        guardrails = NeMoGuardrails()
        classification = {
            "category": "completely_fake_category",
            "recommended_action": "KEEP",
        }
        result = guardrails.validate_classification(classification, {})
        assert result["passed"] is False

    def test_invalid_action_blocked(self):
        """Invalid recommended_action triggers block."""
        from maroon_etl.classify.ontology_bridge import NeMoGuardrails
        guardrails = NeMoGuardrails()
        classification = {
            "category": "governance",
            "recommended_action": "EXPLODE",
        }
        result = guardrails.validate_classification(classification, {})
        assert result["passed"] is False


class TestOntologyBridgeEndToEnd:
    """Test OntologyBridge end-to-end: register, merkle, DAG."""

    def test_register_document_creates_node(self):
        """Registering a document creates a GraphNode in the knowledge graph."""
        from maroon_etl.classify.ontology_bridge import OntologyBridge, ObjectType
        bridge = OntologyBridge()
        node = bridge.register_document("doc_001", "strategy.md", {"cluster": "Business/Strategy"})
        assert node.node_id == "doc_001"
        assert node.object_type == ObjectType.DATA_ASSET

    def test_add_to_merkle_tracks_integrity(self):
        """Adding a document to Merkle DAG enables integrity verification."""
        from maroon_etl.classify.ontology_bridge import OntologyBridge
        bridge = OntologyBridge()
        bridge.register_document("doc_x", "test.md")
        merkle_node = bridge.add_document_to_merkle("doc_x", {
            "content_hash": "abc123",
            "stage": "extracted",
        })
        assert merkle_node.content_hash is not None

    def test_dag_dependency_tracking(self):
        """DAG tracks dependencies between documents."""
        from maroon_etl.classify.ontology_bridge import OntologyBridge
        bridge = OntologyBridge()
        bridge.dag.add_node("doc_a")
        bridge.dag.add_node("doc_b")
        bridge.add_dependency("doc_a", "doc_b")

        # doc_a depends on doc_b, so doc_b should come first in order
        order = bridge.get_build_order()
        assert order.index("doc_b") < order.index("doc_a")

    def test_full_flow_register_merkle_dag(self):
        """Full flow: register doc, add to merkle, track in DAG, verify."""
        from maroon_etl.classify.ontology_bridge import OntologyBridge
        bridge = OntologyBridge()

        # Register two documents
        bridge.register_document("source_doc", "raw-data.csv", {"format": "csv"})
        bridge.register_document("derived_doc", "processed.json", {"format": "json"})

        # Track in Merkle
        bridge.add_document_to_merkle("source_doc", {"hash": "aaa", "stage": "raw"})
        bridge.add_document_to_merkle("derived_doc", {"hash": "bbb", "stage": "curated"})

        # Add dependency
        bridge.dag.add_node("source_doc")
        bridge.dag.add_node("derived_doc")
        bridge.add_dependency("derived_doc", "source_doc")

        # Verify integrity
        integrity = bridge.verify_integrity()
        assert integrity["valid"] is True

        # Get stats
        stats = bridge.get_graph_stats()
        assert stats["graph"]["total_nodes"] == 2
        assert stats["merkle_nodes"] >= 2

    def test_content_hash_static_method(self):
        """OntologyBridge.content_hash computes SHA-256."""
        from maroon_etl.classify.ontology_bridge import OntologyBridge
        h = OntologyBridge.content_hash({"key": "value"})
        assert len(h) == 64
        # Same input produces same hash
        assert h == OntologyBridge.content_hash({"key": "value"})
