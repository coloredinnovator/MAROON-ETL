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
tools/build_rotation_register.py  Builds the rotation worklist
```

Every file in `lake/` carries YAML front-matter with its `drive_file_id`, source
folder, and modification time, so any document traces back to its Drive original.

Extraction is **partial**: the highest-value specs are extracted; the manifest
carries the remaining objects with their Drive IDs and an explicit disposition
each (`extracted`, `pending_extraction`, `s3_only`, `denied`, `review`,
`duplicate`), so extraction resumes without re-surveying.

## Ingest Policy — Rotate From The Lake

`ingest_rules.yaml` is the declarative counterpart to the guardrails table
above. The policy is **rotate from the lake**:

Credential-bearing files are ingested like everything else. Nothing is held
back, nothing is excluded for carrying secrets, and no scan blocks the
pipeline. The lake is the credential *inventory* — it is what tells you what
needs rotating.

`manifest/rotation-register.json` is the worklist that falls out of it. Every
credential found during ingest becomes an entry naming the file, the credential
type, and where to rotate it:

```json
{
  "file": "Maroon-AWS-portable-root/**",
  "credential": "known_credential_location",
  "rotate_at": "Identify each credential inside, then rotate at its provider",
  "status": "pending"
}
```

Work it top to bottom, rotate each at its provider, set `status` to `rotated`.
Re-running the scan carries rotated entries forward, so the register is
cumulative rather than resetting each run:

```bash
python tools/build_rotation_register.py --print
```

It exits 0 on findings — a credential found is a work item, not a build
failure.

### Reconciling with the code rails

Rail A in `src/maroon_etl/guardrails/etl_rails.py` ("No secrets in main lake",
severity `BLOCK`) still hard-blocks. Under rotate-from-the-lake it should
**record to the register instead of blocking**, otherwise the declarative
policy and the code rail disagree and the rail wins at runtime. That change is
flagged, not made — it is Kiro's module.

The `deny` section is now only `.git/` internals and runtime binaries: things
with no analytical value, not a security boundary. PII still routes to the
restricted bucket rather than the main lake, which is placement, not exclusion.

## Shafanna Ontology Integration

This pipeline integrates with the [Shafanna master agent](https://github.com/coloredinnovator/Maroon-Shevette-master-agent) through `vendor/shafanna`:

> **Note on `vendor/shafanna`.** `.gitmodules` declares this a git submodule,
> but it is not one — git records it as a regular tree (`040000`), not a
> gitlink (`160000`). It is a vendored copy of the Shafanna modules, committed
> directly.
>
> Nothing is broken by this: a plain `git clone` gets the code and the tests
> pass. But `git submodule update --init` does nothing useful, and the vendored
> copy has no update path back to the upstream repo, so it will drift silently.
> Either drop `.gitmodules` and treat the vendoring as deliberate (with a
> documented refresh step), or convert it to a real submodule. Right now the
> declaration and the reality disagree.



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

### Bootstrap via AWS CloudShell

The fastest way to provision all infrastructure from scratch is the bootstrap
script. It creates S3 buckets, DynamoDB table, OIDC provider, IAM roles with
scoped policies, and an ECR repository. It is fully idempotent (safe to run
multiple times).

**Steps:**

1. Open [AWS CloudShell](https://us-west-2.console.aws.amazon.com/cloudshell/home?region=us-west-2)
   in the `us-west-2` region (make sure you are in account `496411573616`).

2. Clone this repo and run the bootstrap:

```bash
git clone https://github.com/coloredinnovator/MAROON-ETL.git
cd MAROON-ETL
bash scripts/bootstrap-aws.sh
```

3. After completion the script prints the IAM Role ARNs. Add them as GitHub
   Actions secrets:

| Repository | Secret Name | Value |
|---|---|---|
| `Maroon-Shevette-master-agent` | `AWS_ROLE_ARN` | `arn:aws:iam::496411573616:role/shafanna-github-actions` |
| `MAROON-ETL` | `AWS_ROLE_ARN` | `arn:aws:iam::496411573616:role/maroon-etl-github-actions` |

4. Push any commit to trigger CI/CD with OIDC authentication.

**What gets created:**

| Resource | Name | Notes |
|---|---|---|
| S3 Bucket | `maroon-datalake-496411573616-usw2` | Versioning, SSE-S3, raw/ lifecycle |
| S3 Bucket | `maroon-datalake-restricted-496411573616-usw2` | PII data |
| S3 Bucket | `shafanna-datalake-496411573616` | Shafanna agent |
| DynamoDB | `shafanna-agent-memory` | pk/sk, PAY_PER_REQUEST, TTL |
| OIDC | GitHub Actions provider | No stored credentials |
| IAM Role | `shafanna-github-actions` | Shafanna + maroon-techo repos |
| IAM Role | `maroon-etl-github-actions` | MAROON-ETL repo only |
| ECR | `shafanna-etl` | Container image registry |

All resources are pay-per-use or free tier. Estimated cost: under $0.10/month
with normal usage.

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
