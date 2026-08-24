"""
Tests for MAROON-ETL pipeline.
Validates all modules compile, integrate, and function correctly.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "vendor" / "shafanna"))


# ─── Config Tests ─────────────────────────────────────────────────────

class TestConfig:
    """Test ETLConfig."""

    def test_config_defaults(self):
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert config.MAIN_BUCKET == "maroon-datalake-496411573616-usw2"
        assert config.RESTRICTED_BUCKET == "maroon-datalake-restricted-496411573616-usw2"
        assert config.AWS_REGION == "us-west-2"
        assert config.GDRIVE_FOLDER_ID == "1I43aPmvEJmUfbeDOYkzLh9gFXdkp_gh_"

    def test_config_exclusion_patterns(self):
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert config.is_excluded(".env")
        assert config.is_excluded("kiro_oauth_config.json")
        assert config.is_excluded("path/.git/config")
        assert config.is_excluded(".thumbnails/image.jpg")
        assert not config.is_excluded("document.md")

    def test_config_pii_patterns(self):
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert config.is_pii("john_resume_2024.pdf")
        assert config.is_pii("Facebook Messages export")
        assert config.is_pii("Messenger/chat.json")
        assert config.is_pii("Messages backup")
        assert not config.is_pii("readme.md")

    def test_format_precedence(self):
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        gdoc = config.get_format_precedence("application/vnd.google-apps.document")
        md = config.get_format_precedence("text/markdown")
        pdf = config.get_format_precedence("application/pdf")
        unknown = config.get_format_precedence("application/unknown")
        assert gdoc > md > pdf > unknown

    def test_document_clusters(self):
        from maroon_etl.config.settings import ETLConfig
        config = ETLConfig()
        assert len(config.DOCUMENT_CLUSTERS) == 8
        assert "Business/Strategy" in config.DOCUMENT_CLUSTERS
        assert "Technical/Code" in config.DOCUMENT_CLUSTERS
        assert "Staging/disposal" in config.DOCUMENT_CLUSTERS


# ─── Content Hash Tests ───────────────────────────────────────────────

class TestContentHash:
    """Test SHA-256 content hashing."""

    def test_hash_bytes(self):
        from maroon_etl.extract.content_hash import ContentHasher
        h = ContentHasher.hash_bytes(b"hello world")
        assert len(h) == 64
        assert h == ContentHasher.hash_bytes(b"hello world")  # Deterministic

    def test_hash_string(self):
        from maroon_etl.extract.content_hash import ContentHasher
        h = ContentHasher.hash_string("test content")
        assert len(h) == 64

    def test_hash_dict(self):
        from maroon_etl.extract.content_hash import ContentHasher
        data = {"name": "test", "value": 42}
        h1 = ContentHasher.hash_dict(data)
        h2 = ContentHasher.hash_dict({"value": 42, "name": "test"})
        assert h1 == h2  # Order-independent due to sort_keys

    def test_hash_file(self):
        from maroon_etl.extract.content_hash import ContentHasher
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("file content")
            f.flush()
            h = ContentHasher.hash_file(f.name)
            assert len(h) == 64
        os.unlink(f.name)

    def test_verify(self):
        from maroon_etl.extract.content_hash import ContentHasher
        h = ContentHasher.hash_string("verify me")
        assert ContentHasher.verify("verify me", h)
        assert not ContentHasher.verify("wrong content", h)


# ─── Dedup Tests ──────────────────────────────────────────────────────

class TestDedup:
    """Test deduplication engine."""

    def test_dedup_unique_files(self):
        from maroon_etl.transform.dedup import DedupEngine
        engine = DedupEngine()
        engine.index_file("file1.md", {"content_hash": "aaa", "mime_type": "text/markdown", "size": 100})
        engine.index_file("file2.md", {"content_hash": "bbb", "mime_type": "text/markdown", "size": 200})
        records = engine.deduplicate()
        assert len(records) == 2
        assert engine.stats["duplicate_files"] == 0

    def test_dedup_duplicate_files(self):
        from maroon_etl.transform.dedup import DedupEngine
        engine = DedupEngine()
        engine.index_file("file1.md", {"content_hash": "same", "mime_type": "text/markdown", "size": 100})
        engine.index_file("file2.docx", {"content_hash": "same", "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size": 100})
        records = engine.deduplicate()
        assert len(records) == 1
        assert engine.stats["duplicate_files"] == 1

    def test_dedup_format_precedence(self):
        from maroon_etl.transform.dedup import DedupEngine
        engine = DedupEngine()
        engine.index_file("doc.pdf", {"content_hash": "dup", "mime_type": "application/pdf", "size": 100})
        engine.index_file("doc.md", {"content_hash": "dup", "mime_type": "text/markdown", "size": 100})
        records = engine.deduplicate()
        assert records[0].canonical_mime == "text/markdown"  # .md > PDF

    def test_is_duplicate(self):
        from maroon_etl.transform.dedup import DedupEngine
        engine = DedupEngine()
        engine.index_file("file.md", {"content_hash": "exists", "mime_type": "text/markdown", "size": 100})
        assert engine.is_duplicate("exists")
        assert not engine.is_duplicate("not_exists")


# ─── PII Router Tests ─────────────────────────────────────────────────

class TestPIIRouter:
    """Test PII detection and routing."""

    def test_pii_path_detection(self):
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("john_resume_2024.pdf")
        assert result["action"] == "route_restricted"
        assert result["bucket"] == "maroon-datalake-restricted-496411573616-usw2"

    def test_clean_file(self):
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("readme.md")
        assert result["action"] == "route_main"
        assert result["bucket"] == "maroon-datalake-496411573616-usw2"

    def test_secret_detection(self):
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        content = "api_key = sk-12345abcdef67890"
        result = router.route("config.env", content=content)
        assert result["action"] == "block"

    def test_messenger_pii(self):
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("Facebook Messenger/messages.json")
        assert result["action"] == "route_restricted"

    def test_messages_pii(self):
        from maroon_etl.transform.pii_router import PIIRouter
        router = PIIRouter()
        result = router.route("Messages/conversation_123.json")
        assert result["action"] == "route_restricted"


# ─── Document Classifier Tests ────────────────────────────────────────

class TestDocumentClassifier:
    """Test document classification."""

    def test_classify_technical(self):
        from maroon_etl.classify.document_classifier import DocumentClassifier
        classifier = DocumentClassifier()
        result = classifier.classify("doc-1", "src/main.py", {"mime_type": "text/x-python"})
        assert result.cluster == "Technical/Code"
        assert result.confidence > 0

    def test_classify_business(self):
        from maroon_etl.classify.document_classifier import DocumentClassifier
        classifier = DocumentClassifier()
        result = classifier.classify("doc-2", "business_strategy_2024.md", {"mime_type": "text/markdown"})
        assert result.cluster == "Business/Strategy"

    def test_classify_infra(self):
        from maroon_etl.classify.document_classifier import DocumentClassifier
        classifier = DocumentClassifier()
        result = classifier.classify("doc-3", "terraform/main.tf", {"mime_type": "text/plain"})
        assert result.cluster == "Infra repo mirror"

    def test_classify_unknown_defaults_to_dumpster(self):
        from maroon_etl.classify.document_classifier import DocumentClassifier
        classifier = DocumentClassifier()
        result = classifier.classify("doc-4", "xyz123.bin", {"mime_type": "application/octet-stream"})
        assert result.cluster == "Ingest dumpster"

    def test_classify_guardrails_pass(self):
        from maroon_etl.classify.document_classifier import DocumentClassifier
        classifier = DocumentClassifier()
        result = classifier.classify("doc-5", "readme.md", {"mime_type": "text/markdown"})
        assert result.guardrail_passed is True

    def test_classification_registers_in_graph(self):
        from maroon_etl.classify.document_classifier import DocumentClassifier
        classifier = DocumentClassifier()
        classifier.classify("doc-6", "src/api.py", {"mime_type": "text/x-python"})
        node = classifier.bridge.graph.get_node("doc-6")
        assert node is not None
        assert node.object_type.value == "data_asset"


# ─── Ontology Bridge Tests ────────────────────────────────────────────

class TestOntologyBridge:
    """Test ontology bridge integration."""

    def test_register_document(self):
        from maroon_etl.classify.ontology_bridge import OntologyBridge, ObjectType
        bridge = OntologyBridge()
        node = bridge.register_document("test-doc", "test.md", {"size": 1024})
        assert node.node_id == "test-doc"
        assert node.object_type == ObjectType.DATA_ASSET

    def test_merkle_dag_integration(self):
        from maroon_etl.classify.ontology_bridge import OntologyBridge
        bridge = OntologyBridge()
        mnode = bridge.add_document_to_merkle("doc-1", {"content": "hello"})
        assert mnode.content_hash is not None
        integrity = bridge.verify_integrity()
        assert integrity["valid"] is True

    def test_dag_dependency(self):
        from maroon_etl.classify.ontology_bridge import OntologyBridge
        bridge = OntologyBridge()
        bridge.dag.add_node("a")
        bridge.dag.add_node("b")
        bridge.add_dependency("a", "b")
        order = bridge.get_build_order()
        assert order.index("b") < order.index("a")

    def test_content_hash(self):
        from maroon_etl.classify.ontology_bridge import OntologyBridge
        h = OntologyBridge.content_hash({"key": "value"})
        assert len(h) == 64


# ─── Lineage Tracker Tests ────────────────────────────────────────────

class TestLineageTracker:
    """Test lineage tracking."""

    def test_full_lineage(self):
        from maroon_etl.manifest.lineage import LineageTracker
        tracker = LineageTracker()
        tracker.register_extraction("doc-1", "abc123", "file.md")
        tracker.register_transform("doc-1", "def456", "staged/file.md")
        tracker.register_load("doc-1", "ghi789", "s3://bucket/key", "Technical/Code")
        lineage = tracker.get_lineage("doc-1")
        assert lineage.source_hash == "abc123"
        assert lineage.transform_hash == "def456"
        assert lineage.load_hash == "ghi789"
        assert lineage.pipeline_stage == "loaded"

    def test_manifest_generation(self):
        from maroon_etl.manifest.lineage import LineageTracker
        tracker = LineageTracker()
        tracker.register_extraction("doc-1", "hash1", "file.md")
        manifest = tracker.generate_manifest()
        assert manifest["document_count"] == 1
        assert "merkle_root_hash" in manifest
        assert "integrity" in manifest

    def test_integrity_verification(self):
        from maroon_etl.manifest.lineage import LineageTracker
        tracker = LineageTracker()
        tracker.register_extraction("doc-1", "hash1", "file.md")
        result = tracker.verify_integrity()
        assert result["valid"] is True


# ─── Audit Trail Tests ────────────────────────────────────────────────

class TestAuditTrail:
    """Test audit trail."""

    def test_record_operation(self):
        from maroon_etl.manifest.audit_trail import AuditTrail
        audit = AuditTrail()
        entry = audit.record("extract", "doc-1", output_hash="abc")
        assert entry.operation == "extract"
        assert audit.entry_count == 1

    def test_failure_tracking(self):
        from maroon_etl.manifest.audit_trail import AuditTrail
        audit = AuditTrail()
        audit.record("transform", "doc-1", success=False, error="parse error")
        assert audit.failure_count == 1
        failures = audit.get_failures()
        assert len(failures) == 1

    def test_manifest_generation(self):
        from maroon_etl.manifest.audit_trail import AuditTrail
        audit = AuditTrail()
        audit.record("extract", "doc-1")
        audit.record("transform", "doc-1")
        manifest = audit.generate_manifest()
        assert manifest["total_entries"] == 2
        assert "operations_summary" in manifest


# ─── ETL Guardrails Tests ─────────────────────────────────────────────

class TestETLGuardrails:
    """Test ETL-specific guardrails."""

    def test_secrets_blocked(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        result = guard.validate_content({"content": "api_key = sk-1234567890abcdef"})
        # Should have violations
        assert not result["passed"]

    def test_clean_content_passes(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        result = guard.validate_content({"content": "This is normal document content."})
        assert result["passed"]

    def test_pii_routing_enforced(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        # PII file going to main bucket = violation
        result = guard.validate_routing({
            "file_path": "john_resume.pdf",
            "target_bucket": "maroon-datalake-496411573616-usw2",
        })
        assert not result["passed"]

    def test_pii_routing_correct(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        result = guard.validate_routing({
            "file_path": "john_resume.pdf",
            "target_bucket": "maroon-datalake-restricted-496411573616-usw2",
        })
        assert result["passed"]

    def test_binary_noise_blocked(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        result = guard.validate_extraction({
            "file_path": "chromium_binary.exe",
            "file_name": "chromium_binary.exe",
            "size": 50 * 1024 * 1024,  # 50MB
        })
        assert not result["passed"]

    def test_valid_classification(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        result = guard.validate_classification({"cluster": "Technical/Code"})
        assert result["passed"]

    def test_invalid_classification(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        result = guard.validate_classification({"cluster": "Invalid Category"})
        # Should warn (not block)
        violations = result.get("violations", [])
        assert len(violations) > 0

    def test_rail_names(self):
        from maroon_etl.guardrails.etl_rails import ETLGuardrails
        guard = ETLGuardrails()
        rails = guard.get_rail_names()
        assert "etl_no_secrets_in_main" in rails
        assert "etl_pii_restricted_routing" in rails
        assert "etl_no_binary_noise" in rails
        assert "etl_file_size_limit" in rails
        assert "etl_valid_classification" in rails


# ─── S3 Loader Tests (mocked) ────────────────────────────────────────

class TestS3Loader:
    """Test S3 loader with mocked boto3."""

    @patch("maroon_etl.load.s3_loader.boto3")
    def test_load_bytes(self, mock_boto):
        from maroon_etl.load.s3_loader import S3Loader
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        loader = S3Loader()
        loader._client = mock_client

        result = loader.load_bytes(b"hello", "curated/test.txt")
        assert result["success"] is True
        mock_client.put_object.assert_called_once()

    @patch("maroon_etl.load.s3_loader.boto3")
    def test_load_json(self, mock_boto):
        from maroon_etl.load.s3_loader import S3Loader
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client
        loader = S3Loader()
        loader._client = mock_client

        result = loader.load_json({"key": "value"}, "_manifests/test.json")
        assert result["success"] is True


# ─── Lifecycle Tests ──────────────────────────────────────────────────

class TestLifecycle:
    """Test lifecycle management."""

    def test_get_lifecycle_rules(self):
        from maroon_etl.load.lifecycle import LifecycleManager
        mgr = LifecycleManager()
        rules = mgr.get_lifecycle_rules()
        assert len(rules) == 2
        assert rules[0]["ID"] == "raw-to-glacier-90d"
        assert rules[0]["Transitions"][0]["Days"] == 90
        assert rules[0]["Transitions"][0]["StorageClass"] == "GLACIER"

    def test_athena_pattern(self):
        from maroon_etl.load.lifecycle import LifecycleManager
        mgr = LifecycleManager()
        pattern = mgr.get_athena_pattern()
        assert pattern["status"] == "planned"
        assert "curated_documents" in pattern["tables"]


# ─── Pipeline Integration Test ────────────────────────────────────────

class TestPipeline:
    """Test pipeline orchestrator."""

    def test_pipeline_status(self):
        from maroon_etl.pipeline import Pipeline
        pipeline = Pipeline()
        status = pipeline.status()
        assert "config" in status
        assert status["config"]["main_bucket"] == "maroon-datalake-496411573616-usw2"
        assert "extract_stats" in status
        assert "classifier_stats" in status
        assert "guardrails" in status

    def test_pipeline_init(self):
        from maroon_etl.pipeline import Pipeline
        pipeline = Pipeline()
        assert pipeline.config.MAIN_BUCKET == "maroon-datalake-496411573616-usw2"
        assert pipeline.extractor is not None
        assert pipeline.dedup is not None
        assert pipeline.classifier is not None
        assert pipeline.guardrails is not None
