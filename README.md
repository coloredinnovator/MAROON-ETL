# MAROON-ETL

Stateless batch ETL pipeline for the Maroon data lake. Extracts documents from
Google Drive vault, transforms with deduplication and format normalization,
classifies using Shafanna's semantic ontology, and loads to S3-backed data lake
with full lineage tracking via Merkle DAG integrity verification.

## Architecture

```
Google Drive Vault (42 items)
        |
        v
   [Extract] --- exclusion filter, content hashing
        |
        v
  raw/ zone (S3)
        |
        v
  [Transform] --- dedup (SHA-256), format convert, PII routing
        |
        v
  staged/ zone (S3)
        |
        v
   [Classify] --- KnowledgeGraph + SemanticLayer + NeMoGuardrails
        |
        v
  curated/ zone (S3) + _manifests/
```

## Budget Constraint

**Target: UNDER $0.10/month**

- S3 Standard for active data, Glacier for raw/ after 90 days
- Athena pay-per-query (future)
- DeepSeek V3 on Bedrock: $0.14/1M input tokens
- Zero idle compute (no always-on services)
- OIDC auth only (no stored credentials)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run full pipeline
python -m maroon_etl run

# Run individual phases
python -m maroon_etl extract
python -m maroon_etl transform
python -m maroon_etl load

# Check status
python -m maroon_etl status
```

## S3 Layout

```
maroon-datalake-496411573616-usw2/
  raw/              <- extracted from Drive (Glacier at 90d)
  staged/           <- after dedup + format normalization
  curated/          <- classified, production-ready
  _manifests/       <- lineage, audit, dedup reports
    audit/          <- per-run audit trails
    lineage.json    <- Merkle DAG integrity proofs
    dedup.json      <- deduplication manifest

maroon-datalake-restricted-496411573616-usw2/
  (PII-containing files routed here)
```

## Extracted Corpus (`lake/`)

The pipeline above produces S3 zones. Separately, `lake/` holds vault documents
already extracted to Markdown and committed here, so agents get vault context by
cloning the repo — no Drive credentials, no S3 dependency:

```bash
git clone https://github.com/coloredinnovator/MAROON-ETL.git
# context is in lake/ as plain Markdown
```

Per Directive 8 the GitHub repository is the *permanent source of truth* and the
layer AI agents read from, which is why the corpus lives in git rather than only
in object storage.

```
lake/
  00_root/                  Loose documents at the vault root
  01_business_strategy/
  02_technical_and_code/
  03_marketing_and_operations/
  04_legal_compliance/
manifest/vault-manifest.json   Provenance for all 65 vault objects
ingest_rules.yaml              Declarative ingest policy
tools/scan_secrets.py          Standalone policy check
```

Every file in `lake/` carries YAML front-matter with its `drive_file_id`, source
folder, and modification time, so any document traces back to its Drive original.

Extraction is **partial**: the highest-value specs are extracted; the manifest
carries the remaining objects with their Drive IDs and an explicit disposition
each (`extracted`, `pending_extraction`, `s3_only`, `denied`, `review`,
`duplicate`, `rotate_before_ingest`), so extraction resumes without re-surveying.

## Ingest Policy and the Rotation Gate

`ingest_rules.yaml` is the declarative counterpart to the guardrails table above.
Two things about it differ from the code rails and need reconciling:

**1. Secrets are gated on ordering, not excluded.** Owner decision (2026-08-23):
the credential-bearing files are *not* permanently excluded — they belong in the
lake, and the credentials will be rotated. `rotate_before_ingest` therefore holds
them only until rotation happens, then releases them. The reasoning is that git
history is permanent: a credential committed and then rotated stays readable
forever, while one rotated first is already dead when it lands. Same destination,
safe order.

To release: rotate, set `rotate_before_ingest.rotated: true`, and those files
ingest on the next run like anything else.

This is in tension with Rail A ("No secrets in main lake", severity BLOCK) in
`src/maroon_etl/guardrails/etl_rails.py`, which hard-blocks rather than gates.
**The two should be reconciled before a production run** — right now the
declarative policy and the code rail disagree.

**2. `tools/scan_secrets.py` overlaps `etl_rails.py`.** Both scan for AWS keys,
JWTs, Slack tokens, and private keys. Maintaining two scanners that can drift
apart is worse than one; consolidating them (likely by having `etl_rails.py` read
`ingest_rules.yaml`) is worth doing, but is left as an explicit decision rather
than resolved unilaterally in a merge.

## Shafanna Ontology Integration

This pipeline integrates with the [Shafanna master agent](https://github.com/coloredinnovator/Maroon-Shevette-master-agent) via git submodule:

- **KnowledgeGraph**: Every document is a `GraphNode` with `ObjectType.DATA_ASSET`
- **SemanticLayer**: Documents get interface assignments (ARCHIVABLE, SECURED, etc.)
- **MerkleDAG**: Content-addressable integrity verification through all pipeline stages
- **DAG**: Document dependency tracking and processing order
- **NeMoGuardrails**: Safety rails prevent secrets/PII from entering main lake
- **BedrockDeepSeek**: AI-powered document classification (when available)

## Document Classification (8 Clusters)

Based on Drive vault survey:

1. **Business/Strategy** - roadmaps, proposals, financials
2. **Technical/Code** - source code, READMEs, configs
3. **Infra repo mirror** - Terraform, Docker, CI/CD
4. **Legal/Healthcare** - HIPAA, contracts, compliance
5. **Marketing/Ops** - campaigns, playbooks, brand
6. **Ingest dumpster** - temp files, caches, untitled docs
7. **Device backup** - phone backups, photos, screenshots
8. **Staging/disposal** - deprecated, archived, trash

## Deduplication

SHA-256 content hashing identifies duplicates (expected 60-70% by volume).
Format precedence selects canonical version:

```
Google Doc > .md > .docx > PDF
```

## Guardrails

ETL-specific NeMo-style rails:

| Rail | Type | Severity | Description |
|------|------|----------|-------------|
| No secrets in main lake | SAFETY | BLOCK | API keys, passwords, private keys |
| PII restricted routing | SAFETY | BLOCK | Resume, Messages, Messenger, Facebook |
| Binary noise filter | INPUT | BLOCK | Chromium/Electron > 10MB |
| File size limit | INPUT | BLOCK | Max 100MB per file |
| Valid classification | SCHEMA | WARN | Must match 8 valid clusters |

## Configuration

Key settings in `src/maroon_etl/config/settings.py`:

- Main bucket: `maroon-datalake-496411573616-usw2`
- Restricted bucket: `maroon-datalake-restricted-496411573616-usw2`
- Drive folder: `1I43aPmvEJmUfbeDOYkzLh9gFXdkp_gh_`
- Region: `us-west-2`
- Account: `496411573616`

## Infrastructure

Terraform in `terraform/main.tf`:
- Two S3 buckets (main + restricted) with versioning and SSE-S3
- Lifecycle rules (raw/ to Glacier at 90 days)
- IAM role with OIDC for GitHub Actions
- Public access blocked on both buckets

## Future State (NOT built now)

- Apache Spark for large-scale transforms
- MinIO for local development
- Apache Iceberg for table format
- Airflow/MWAA for orchestration
- Glue Catalog + Athena for SQL queries

## AWS

- Account: 496411573616
- Region: us-west-2
- Auth: OIDC only (GitHub Actions, EC2 instance profile)
- Owner: wffoodgroup@gmail.com

## Testing

```bash
pytest tests/ -v
```

## Docker

```bash
docker build -t maroon-etl .
docker run maroon-etl status
```
