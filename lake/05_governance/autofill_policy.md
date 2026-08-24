---
source: google_drive
drive_file_id: 1PT2_iCPBi-sg14f69pK6JU7MJV6MI3R-
drive_archive: 'Dynasty_Master_Governance_Files_Full (1).zip'
archive_member: Autofill_Policy.md
drive_folder: _archive_extracted
archive_modified: 2025-10-30T02:41:18Z
extracted_via: zip_expansion
classification: governance
---

# Autofill Policy — Fill the Gaps Like a Mission Control Engineer

**Owner:** MoSK  
**Mandate:** Never leave a blank. Always draft, mark assumptions, and tag review.  

---

## Workflow
1. **Source-First**: scan Drive/repo, insert evidence, cite provenance.  
2. **Infer-Smartly**: if thin, generate Option A/B with rationale.  
3. **Flag-Risk**: requires_review=true for legal/finance.  
4. **Stamp**: add Assumptions + Next Data Needed.  
5. **Escalate**: Sean (legal), Founder (IP), Finance Pro (finance).  

---

## Metadata Schema
```yaml
title: string
owner: "MoSK"
status: [draft|living|final]
version: semver
last_updated_utc: ISO-8601
labels: [array]
provenance:
  source_docs: [paths or IDs]
  confidence: [low|med|high]
  requires_review: bool
```

---

## Prohibited
- ❌ Fake legal facts or signatures.  
- ❌ Insert PII.  
- ❌ Call assumptions “final.”  
