"""
MAROON-ETL: Stateless batch ETL pipeline for the Maroon data lake.

Extracts documents from Google Drive vault, transforms with deduplication
and format normalization, classifies using Shafanna's ontology, and loads
to S3-backed data lake with full lineage tracking.

Architecture:
    Google Drive -> extract -> transform -> classify -> load -> S3
                                                              |
    Ontology (KnowledgeGraph, SemanticLayer, NeMoGuardrails) -+
                                                              |
    Merkle DAG integrity verification throughout             -+

Budget target: UNDER $0.10/month (S3 + Athena only)
AWS Account: 496411573616, us-west-2
Auth: OIDC only (zero stored credentials)
"""

__version__ = "0.1.0"
__author__ = "Maroon Technologies"
__project__ = "MAROON-ETL"
