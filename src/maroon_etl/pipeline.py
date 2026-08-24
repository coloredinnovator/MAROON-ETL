"""
MAROON-ETL Master Pipeline Orchestrator.

Stateless batch execution: extract -> transform -> load.
Idempotent: can re-run safely using content hashes to skip already-processed files.
Rich console output for visibility.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import Progress
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

from .config.settings import ETLConfig
from .extract.content_hash import ContentHasher
from .extract.gdrive_extractor import GDriveExtractor
from .transform.dedup import DedupEngine
from .transform.format_converter import FormatConverter
from .transform.pii_router import PIIRouter
from .classify.document_classifier import DocumentClassifier
from .load.s3_loader import S3Loader
from .load.lifecycle import LifecycleManager
from .manifest.lineage import LineageTracker
from .manifest.audit_trail import AuditTrail
from .guardrails.etl_rails import ETLGuardrails


class Pipeline:
    """
    Master ETL pipeline orchestrator.
    Stateless batch: extract -> transform -> classify -> load.
    """

    def __init__(self, config: Optional[ETLConfig] = None):
        self.config = config or ETLConfig()
        self.console = Console() if HAS_RICH else None

        # Pipeline components
        self.extractor = GDriveExtractor(self.config)
        self.dedup = DedupEngine(self.config)
        self.converter = FormatConverter(self.config)
        self.pii_router = PIIRouter(self.config)
        self.classifier = DocumentClassifier(self.config)
        self.loader = S3Loader(self.config)
        self.lifecycle = LifecycleManager(self.config)
        self.lineage = LineageTracker()
        self.audit = AuditTrail()
        self.guardrails = ETLGuardrails(self.config)

        # Pipeline state
        self._processed_hashes: set[str] = set()
        self._start_time: Optional[float] = None

    def run(self, data_dir: str = "data") -> dict:
        """
        Execute the full pipeline: extract -> transform -> classify -> load.

        Args:
            data_dir: Base directory for pipeline data.

        Returns:
            Pipeline execution results.
        """
        self._start_time = time.time()
        self._print("[bold green]MAROON-ETL Pipeline Starting[/bold green]")
        self._print(f"  Config: {self.config.MAIN_BUCKET}")
        self._print(f"  Region: {self.config.AWS_REGION}")
        self._print(f"  Source: Drive folder {self.config.GDRIVE_FOLDER_ID}")
        self._print("")

        raw_dir = str(Path(data_dir) / "raw")
        staged_dir = str(Path(data_dir) / "staged")
        curated_dir = str(Path(data_dir) / "curated")

        # Phase 1: Extract
        self._print("[bold blue]Phase 1: Extract[/bold blue]")
        extract_result = self._run_extract(raw_dir)

        # Phase 2: Transform (dedup + convert + PII route)
        self._print("\n[bold blue]Phase 2: Transform[/bold blue]")
        transform_result = self._run_transform(raw_dir, staged_dir)

        # Phase 3: Classify
        self._print("\n[bold blue]Phase 3: Classify[/bold blue]")
        classify_result = self._run_classify(staged_dir)

        # Phase 4: Load
        self._print("\n[bold blue]Phase 4: Load[/bold blue]")
        load_result = self._run_load(staged_dir, curated_dir)

        # Generate manifests
        self._print("\n[bold blue]Generating Manifests[/bold blue]")
        manifests = self._generate_manifests(data_dir)

        elapsed = time.time() - self._start_time
        self._print(f"\n[bold green]Pipeline Complete[/bold green] ({elapsed:.2f}s)")

        return {
            "success": True,
            "elapsed_seconds": elapsed,
            "extract": extract_result,
            "transform": transform_result,
            "classify": classify_result,
            "load": load_result,
            "manifests": manifests,
        }

    def run_extract(self, output_dir: str = "data/raw") -> dict:
        """Run only the extract phase."""
        self._start_time = time.time()
        self._print("[bold blue]Running Extract Phase[/bold blue]")
        return self._run_extract(output_dir)

    def run_transform(self, raw_dir: str = "data/raw", staged_dir: str = "data/staged") -> dict:
        """Run only the transform phase."""
        self._start_time = time.time()
        self._print("[bold blue]Running Transform Phase[/bold blue]")
        return self._run_transform(raw_dir, staged_dir)

    def run_load(self, staged_dir: str = "data/staged", curated_dir: str = "data/curated") -> dict:
        """Run only the load phase."""
        self._start_time = time.time()
        self._print("[bold blue]Running Load Phase[/bold blue]")
        return self._run_load(staged_dir, curated_dir)

    def _run_extract(self, raw_dir: str) -> dict:
        """Internal: run extraction."""
        result = self.extractor.extract(output_dir=raw_dir)
        for file_meta in result.get("files", []):
            doc_id = file_meta.get("content_hash", "")[:16]
            source_hash = file_meta.get("content_hash", "")
            self.lineage.register_extraction(doc_id, source_hash, file_meta.get("original_name", ""))
            self.audit.record("extract", doc_id, output_hash=source_hash)
        self._print(f"  Extracted: {result.get('stats', {}).get('files_extracted', 0)} files")
        return result

    def _run_transform(self, raw_dir: str, staged_dir: str) -> dict:
        """Internal: run transformation (dedup + convert + PII route)."""
        raw_path = Path(raw_dir)
        results = {"dedup": {}, "converted": 0, "pii_routed": 0, "skipped": 0}

        if not raw_path.exists():
            self._print("  No raw data found. Skipping transform.")
            return results

        # Process all files in raw/
        for meta_file in raw_path.glob("*.meta.json"):
            try:
                metadata = json.loads(meta_file.read_text())
                file_name = metadata.get("output_name", meta_file.stem.replace(".meta", ""))
                file_path = str(raw_path / file_name)
                content_hash = metadata.get("content_hash", "")

                # Idempotency: skip already-processed
                if content_hash in self._processed_hashes:
                    results["skipped"] += 1
                    continue

                # Index for dedup
                self.dedup.index_file(file_path, metadata)

                # PII routing check
                routing = self.pii_router.route(file_path)
                if routing["action"] == "block":
                    self.audit.record("transform", content_hash[:16],
                                      metadata={"action": "blocked_secret"})
                    continue
                if routing["action"] == "route_restricted":
                    results["pii_routed"] += 1

                # Format conversion
                converted = self.converter.convert(file_path, metadata, staged_dir)
                if converted:
                    results["converted"] += 1
                    doc_id = content_hash[:16]
                    transform_hash = converted.get("output_hash", "")
                    self.lineage.register_transform(doc_id, transform_hash, converted.get("output_file", ""))
                    self.audit.record("transform", doc_id, input_hash=content_hash, output_hash=transform_hash)

                self._processed_hashes.add(content_hash)

            except Exception as e:
                self.audit.record("transform", str(meta_file), success=False, error=str(e))

        # Run dedup
        results["dedup"] = self.dedup.stats
        self._print(f"  Converted: {results['converted']}, PII routed: {results['pii_routed']}")
        self._print(f"  Dedup: {self.dedup.stats.get('duplicate_files', 0)} duplicates found")
        return results

    def _run_classify(self, staged_dir: str) -> dict:
        """Internal: run classification."""
        staged_path = Path(staged_dir)
        results = {"classified": 0, "by_cluster": {}}

        if not staged_path.exists():
            self._print("  No staged data found. Skipping classify.")
            return results

        for file_path in staged_path.iterdir():
            if file_path.is_file() and not file_path.name.endswith(".meta.json"):
                doc_id = ContentHasher.hash_file(str(file_path))[:16]
                metadata = {"mime_type": "text/plain", "size": file_path.stat().st_size}
                classification = self.classifier.classify(doc_id, str(file_path), metadata)
                self.audit.record(
                    "classify", doc_id,
                    metadata={"cluster": classification.cluster, "confidence": classification.confidence},
                )
                results["classified"] += 1

        results["by_cluster"] = self.classifier.stats["by_cluster"]
        self._print(f"  Classified: {results['classified']} documents")
        return results

    def _run_load(self, staged_dir: str, curated_dir: str) -> dict:
        """Internal: run load to S3."""
        staged_path = Path(staged_dir)
        results = {"loaded": 0, "errors": 0}

        if not staged_path.exists():
            self._print("  No staged data found. Skipping load.")
            return results

        for file_path in staged_path.iterdir():
            if file_path.is_file() and not file_path.name.endswith(".meta.json"):
                s3_key = f"{self.config.CURATED_PREFIX}{file_path.name}"
                routing = self.pii_router.route(str(file_path))
                bucket = routing.get("bucket", self.config.MAIN_BUCKET)

                if bucket is None:
                    continue  # Blocked

                try:
                    load_result = self.loader.load_file(
                        str(file_path), s3_key, bucket=bucket
                    )
                    if load_result.get("success"):
                        results["loaded"] += 1
                        doc_id = ContentHasher.hash_file(str(file_path))[:16]
                        load_hash = ContentHasher.hash_file(str(file_path))
                        self.lineage.register_load(doc_id, load_hash, load_result.get("s3_uri", ""))
                        self.audit.record("load", doc_id, output_hash=load_hash,
                                          metadata={"s3_uri": load_result.get("s3_uri", "")})
                    else:
                        results["errors"] += 1
                except Exception as e:
                    results["errors"] += 1
                    self.audit.record("load", str(file_path), success=False, error=str(e))

        self._print(f"  Loaded: {results['loaded']}, Errors: {results['errors']}")
        return results

    def _generate_manifests(self, data_dir: str) -> dict:
        """Generate all pipeline manifests."""
        manifest_dir = Path(data_dir) / "_manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        # Lineage manifest
        lineage_manifest = self.lineage.generate_manifest()
        lineage_path = manifest_dir / "lineage.json"
        lineage_path.write_text(json.dumps(lineage_manifest, indent=2, default=str))

        # Audit manifest
        audit_path = self.audit.save_local(str(manifest_dir / "audit"))

        # Dedup manifest
        dedup_manifest = self.dedup.generate_manifest()
        dedup_path = manifest_dir / "dedup.json"
        dedup_path.write_text(json.dumps(dedup_manifest, indent=2, default=str))

        # PII routing manifest
        pii_manifest = self.pii_router.get_manifest()
        pii_path = manifest_dir / "pii_routing.json"
        pii_path.write_text(json.dumps(pii_manifest, indent=2, default=str))

        self._print(f"  Manifests written to: {manifest_dir}")
        return {
            "lineage": str(lineage_path),
            "audit": audit_path,
            "dedup": str(dedup_path),
            "pii_routing": str(pii_path),
        }

    def status(self) -> dict:
        """Get pipeline status and statistics."""
        return {
            "config": {
                "main_bucket": self.config.MAIN_BUCKET,
                "restricted_bucket": self.config.RESTRICTED_BUCKET,
                "region": self.config.AWS_REGION,
                "folder_id": self.config.GDRIVE_FOLDER_ID,
            },
            "extract_stats": self.extractor.stats,
            "dedup_stats": self.dedup.stats,
            "converter_stats": self.converter.stats,
            "pii_stats": self.pii_router.stats,
            "classifier_stats": self.classifier.stats,
            "loader_stats": self.loader.stats,
            "audit": {
                "entries": self.audit.entry_count,
                "failures": self.audit.failure_count,
            },
            "lineage": {
                "documents": len(self.lineage._lineage),
                "integrity": self.lineage.verify_integrity(),
            },
            "guardrails": self.guardrails.stats,
        }

    def _print(self, message: str) -> None:
        """Print with Rich if available, otherwise plain."""
        if self.console and HAS_RICH:
            self.console.print(message)
        else:
            # Strip Rich markup for plain output
            import re
            clean = re.sub(r"\[/?[^\]]+\]", "", message)
            print(clean)
