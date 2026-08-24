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

The vault's `Maroon-AWS-portable-root` mirror carries a live `.env` and
`kiro_oauth_config.json`, and the Drive folder is shared by link.

Per owner decision (2026-08-23) these are **not** permanently excluded — they
are destined for the lake. What `ingest_rules.yaml` enforces is *ordering*, not
exclusion:

- `rotate_before_ingest` holds those files until the credentials are rotated.
  Git history is permanent, so a credential committed and then rotated stays
  readable forever, while a credential rotated first is already dead when it
  lands. Same end state; only the safe order is enforced.
- To release: rotate, set `rotate_before_ingest.rotated: true`, and they ingest
  on the next run like anything else.

Still hard-denied, and separate from the above: synced `.git/` internals,
personal data (a resume misfiled under `04_Legal_Healthcare_Compliance`, phone
backups under `DCIM/`, `Pictures/`, `Download/`), and ~90MB of Chromium runtime
libraries. Say the word if any of those should move into the lake too.

`tools/scan_secrets.py` enforces all of this and exits non-zero on a hit, so it
can gate CI or a pre-commit hook. It is verified in both directions — clean on
the current lake, and catching planted keys and blocked filenames.

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
