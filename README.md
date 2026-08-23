# MAROON-ETL

ETL for the **MAROON_MASTER_DYNASTY_VAULT** Google Drive folder into a queryable
datalake. This repository is the text-extracted corpus plus the tooling that
produces it.

Per the Directive 8 architecture, the GitHub repository is the *permanent source
of truth* and the layer AI agents read from. Kiro and Claude Code get vault
context by reading `lake/` here — not by holding Drive credentials.

## Layout

```
lake/                     Extracted documents, one Markdown file per source doc
  00_root/                Loose documents at the vault root
  01_business_strategy/
  02_technical_and_code/
  03_marketing_and_operations/
  04_legal_compliance/
manifest/vault-manifest.json   Provenance for every vault object
ingest_rules.yaml         What may be ingested, and what may never be
tools/                    Extraction and S3 sync
```

Every file in `lake/` carries YAML front-matter with its `drive_file_id`,
source folder, and modification time, so any document can be traced back to
its Drive original.

## How Kiro gets this

```bash
git clone https://github.com/coloredinnovator/MAROON-ETL.git
# vault context is in lake/ — plain Markdown, no credentials needed
```

Once the S3 datalake exists, full-fidelity originals (including binaries too
large for git) live at
`s3://shafanna-datalake-<account>/etl/gdrive/dynasty-vault/`.

## Security posture

`SECURITY.md` under Directive 8 states a **zero secrets in GitHub** rule. This
pipeline enforces it mechanically, not by convention:

- `ingest_rules.yaml` hard-denies credential files, the `Maroon-AWS-portable-root/**`
  mirror, synced `.git/` internals, PII, and phone backups.
- Every surviving file is regex-scanned for key material before it lands, and a
  hit **fails the run** rather than skipping quietly.

The source Drive folder is shared by link and contains a live `.env` and
`kiro_oauth_config.json` inside the `Maroon-AWS-portable-root` mirror. Those
credentials should be rotated and the share narrowed. They are excluded here by
policy, but exclusion from this repo does not undo their exposure in Drive.

## Status

| Piece | State |
| :-- | :-- |
| Vault survey and classification | Done |
| Ingest policy | Done |
| Text extraction | Partial — highest-value specs extracted; manifest covers the rest |
| S3 datalake | **Not created.** Terraform has never been applied. |
| Automated refresh | Blocked on S3 and on Drive service-account credentials |

The S3 blocker is documented in
`Maroon-Shevette-master-agent/docs/AUDIT-2026-08-23.md`.
