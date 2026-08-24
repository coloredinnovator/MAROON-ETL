# Archive Audit — Drive Vault Zips

Findings from opening the vault's archive files. Two of these correct the
earlier vault survey; one is a gap in the current pipeline.

## 1. The pipeline does not open archives

`src/maroon_etl/` has no archive expansion. The only `zipfile` usage is in
`transform/format_converter.py`, and it is there to read `word/document.xml`
out of `.docx` — not to expand `.zip` members.

Consequence: every `.zip` in the vault is ingested as **one opaque binary
blob**. Its contents are never extracted, hashed, classified, or made
searchable. There are 40+ archives in the vault (first page of results alone),
and they are not junk — they hold governance files, patent packages, banker
documents, and pilot packs.

## 2. Dedup is defeated by nesting

`Dynasty_Master_Governance_Files_Full (1).zip` (46,728 bytes) contains 16
governance documents **plus two nested zips**:

```
Dynasty_Master_Governance_Files_Full (1).zip
├── 16 governance files (Master_Index.md, Filing_Status.md, …)
├── Dynasty_Master_Governance_Files_Full (2) (1).zip   ← same 16 files
└── Dynasty_Master_Governance_Files_Full (4).zip
    └── Dynasty_Master_Governance_Files_Full (2).zip   ← same 16 files again
```

The same 16 documents, wrapped three levels deep.

`transform/dedup.py` hashes the **container**, not the members. Three
containers with identical contents produce three different SHA-256 values, so
all three are retained as "unique." The stated 60–70% duplication estimate is
therefore likely an *undercount*, because recursive archive duplication is
invisible to the current hashing strategy.

Fixing this means expanding archives before hashing, and hashing members rather
than containers.

## 3. Two archives exceed the 100MB rail

Rail D (`etl_file_size_limit`, severity BLOCK) rejects files over 100MB. Two
vault archives are blocked by it:

| Archive | Size | Assessment |
| :-- | --: | :-- |
| `takeout-20251204T172236Z-8-001.zip` | 275 MB | Google Takeout — **may contain real documents**; worth opening before it is written off |
| `cb_2019_53_bg_500k.zip` | 226 MB | Census TIGER block groups, WA (FIPS 53) — public reference data, safely skippable |

The census file is correctly skipped. The Takeout archive is a judgment call
that should be made deliberately rather than by a size threshold.

Note the 10MB `BINARY_SIZE_LIMIT_MB` rail does **not** drop these — it only
fires when a file is both >10MB *and* matches a Chromium/Electron name pattern.
That design is correct and is not the cause here.

## 4. Corrections to the earlier vault survey

- **Date range.** The earlier survey said the oldest object was 2025-10-31. It
  is not. `Sean bundel .zip` carries a modified time of **2025-10-14T19:18:10Z**,
  and several other archives fall between the 14th and the 31st. The corpus
  reaches back roughly two weeks further than reported.
- **Duplication.** The earlier survey attributed most byte volume to "five
  copies of one census zip." The dominant single object is the 226MB
  `cb_2019_53_bg_500k.zip`, with smaller sibling copies (2.1MB, 1.37MB ×3) and a
  separate 275MB Takeout archive. The shape of the claim held; the numbers did
  not.

## 5. What was extracted

`Dynasty_Master_Governance_Files_Full (1).zip` expanded cleanly (integrity
check OK) and its 16 governance documents are now in `lake/05_governance/`,
each carrying `drive_archive` and `archive_member` front-matter so it traces
back to its container.

Contents are a governance operating system: `Master_Index.md`,
`Operating_Model.md`, `Filing_Status.md` (patent/regulatory/corporate status
tracker), `TODO_List.md`, `ChangeLog.md`, `Autofill_Policy.md`,
`Review_Checklists.md`, and nine cadence command scripts (daily through yearly,
plus IPO, emergency, and shutdown protocols).

`Filing_Status.md` is live operational data, not a template — it tracks three
patents (two not started, one in draft), Reg C/Reg CF status, SBA loan packets,
and the Dynasty Trust instrument.

## Recommended fix

Add an archive-expansion stage between extract and transform:

1. Expand `.zip` recursively, with a depth cap and a total-uncompressed-size cap
   (zip-bomb protection — the nesting seen here is benign, but the cap should
   exist before this runs unattended).
2. Hash and dedup **members**, not containers.
3. Run the existing guardrails on each member, so secret and PII rails apply
   inside archives rather than only to their filenames.
4. Decide the >100MB Takeout archive explicitly rather than by threshold.

Until then, treat archive contents as outside the lake.
