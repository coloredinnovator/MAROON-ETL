---
source: google_drive
drive_file_id: 1gBOyVpZ-PGs8wkHs0YbIeryPBsUEeAK4BuRVQvloDNc
drive_folder: 02_Technical_and_Code
title: MAROON AI OPERATING ENVIRONMENT, DIRECTIVE 8 REPO ARCHITECTURE & KIRO/CLAUDE AGENT SPECIFICATION
mime_type: application/vnd.google-apps.document
created: 2026-08-04T01:47:30.946Z
modified: 2026-08-04T01:48:17.927Z
extracted_via: drive_export_markdown
classification: technical_spec

# MAROON AI OPERATING ENVIRONMENT, DIRECTIVE 8 REPO ARCHITECTURE & KIRO/CLAUDE AGENT SPECIFICATION

**Author & Sovereign Lead:** Emmanuel Washington, CEO & Founder
**Ecosystem System Classification:** Harvard-Grade Sovereign AI Operating Environment & Cloud Workspace
**Target Architecture Version:** 5.2.0 (Directive 8 Release)

## SECTION 1: ENTERPRISE VISION ("PALANTIR / IBM / ORACLE OPERATING OS")

### 1.1 The Cloud-Native Sovereign Environment

The Maroon AI Operating Environment establishes a portable, enterprise-grade operating system designed for autonomous execution without vendor lock-in. Modeled on top-tier enterprise data architectures (Palantir, IBM, Oracle), the system enforces a strict separation of concerns across five core layers:

1. **Human Sovereign (Decision Maker)**: Emmanuel Washington establishes intent, legal boundaries, and strategic direction.
2. **AI Interfaces (Interchangeable Agents)**: Kiro, Claude Code, Amazon Q, and future agents operate as temporary execution interfaces.
3. **MCP / APIs / Approved Connectors**: Model Context Protocol (MCP) provides secure, controlled access to external tools, databases, and cloud services.
4. **Cloud Execution Machine**: AWS (Primary execution machine), GCP (Legacy migration source), and Azure (Reserve free-tier pool).
5. **GitHub Repository (Permanent Source of Truth)**: The authoritative memory layer holding all source code, system documentation, business context, and operational directives.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      HUMAN SOVEREIGN (Emmanuel)                         │
│                    (Intent, Policy & Sign-Off Gate)                     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             AI INTERFACE LAYER (Interchangeable Agents)                  │
│       Kiro (Spec-Driven) │ Claude Code │ Amazon Q / Future Agents        │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             MCP / API CONNECTOR LAYER (Secure Tooling)                   │
│       GitHub MCP │ AWS IAM SSO │ PostGIS │ Neo4j │ Cloud Run             │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             CLOUD EXECUTION MACHINE (The Infrastructure)                 │
│   Primary: AWS Linux Workspace VM │ Secondary: GCP Pipeline / Azure      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│            GITHUB REPOSITORY (Permanent Memory & Source of Truth)        │
│      maroon-technologies org │ Directive 8 10-File Structure             │
└─────────────────────────────────────────────────────────────────────────┘
```

## SECTION 2: DIRECTIVE 8 STANDARD REPOSITORY STRUCTURE (10 CORE FILES)

Every repository across the Maroon ecosystem MUST instantiate the Directive 8 standard file structure to guarantee immediate context ingestion for any AI assistant:

| File Name | Purpose |
| :-- | :-- |
| README.md | System entry point & quickstart |
| PROJECT_CONTEXT.md | Business context & corporate chain |
| ARCHITECTURE.md | Technical stack & account boundaries |
| RUNBOOK.md | Daily step-by-step workflow |
| SECURITY.md | Legal/security gates & sign-offs |
| INFRASTRUCTURE.md | AWS/GCP cloud setups & VM rules |
| CHANGELOG.md | Historical decision log |
| CLAUDE.md | AI posture & Harvard-grade style bar |
| docs/ai-operating-environment-directive.md | Canonical 12 directives |
| docs/maroon-migration-brief.md | Migration & audit master brief |

### 2.1 File Specification Breakdown

1. **README.md**: Repository entry point establishing project purpose, installation steps, and quickstart commands.
2. **PROJECT_CONTEXT.md**: Canonical business picture detailing the corporate chain (**Maroon Trust** -> **Maroon Foods** -> **Onita's Market**) and active priority builds (Onita's Market, Mac Ave, cedar-app-nw, Maroon Social, bee-prec, Sean & Adrian Legal Site).
3. **ARCHITECTURE.md**: System layer diagram, cloud account mappings (maroon-tech us-east-1 on AWS, legacy GCP), domain mapping (maroon-technologies.org on Cloudflare), and 3-account GitHub landscape (coloredinnovator-ai, production account, student dev pack).
4. **RUNBOOK.md**: Step-by-step daily workflow (Authenticate AWS SSO -> Authenticate GitHub -> Launch VS Code -> Connect AWS Linux VM -> Execute work), model selection policies (opusplan / --model opus for reasoning vs. Sonnet for execution), and Ponytail token reduction steps (~54% token savings).
5. **SECURITY.md**: Non-negotiable legal guardrails: AWS IAM Identity Center SSO enforcement, **zero secrets in GitHub rule**, and mandatory Emmanuel sign-off for irreversible actions (deletions, account changes, real money spent).
6. **INFRASTRUCTURE.md**: AWS primary execution environment, GCP pipeline migration status, Azure reserve compute, standing Linux workspace VM rules, and container configs.
7. **CHANGELOG.md**: Historical decision ledger recording architecture evolutions and system changes.
8. **CLAUDE.md**: AI posture ("Hired Firm" ownership energy), Harvard-grade master-coder style bar, and plain-language reporting guidelines.
9. **docs/ai-operating-environment-directive.md**: The canonical 12 platform directives governing portable AI execution.
10. **docs/maroon-migration-brief.md**: Comprehensive 56-repo taxonomy, GCP-to-AWS migration plan, and full audit brief.

## SECTION 3: AI INTERFACE TOOLING & TOOL SUNSET MITIGATION

### 3.1 Amazon Q Developer Sunset Timeline

AWS officially announced the deprecation of Amazon Q Developer's IDE plugins and paid subscriptions:

- **May 15, 2026**: New user signups for Amazon Q Developer IDE subscriptions blocked.
- **April 30, 2027**: Full end-of-support and final shutdown of Amazon Q Developer IDE plugins.

### 3.2 Product Differentiation: Amazon Q Business vs. Amazon Q Developer

- **Amazon Q Business**: Enterprise search and internal document discovery engine operating over AWS data stores. *Stays active*.
- **Amazon Q Developer**: IDE coding assistant and developer extension. *On sunset path*.

### 3.3 Migration Path: Kiro, Claude Code & Spec-Driven Agents

To prevent build disruption, Maroon platform migrates developer workflows to **Kiro** and **Claude Code**:

- **Kiro Integration**: Spec-driven AI agent environment that enforces structured design-before-code workflows (AGENT_RULES.schema, SYSTEM_SPEC.yaml).
- **Claude Code**: Primary terminal-centric execution agent executing Plan Mode, subagent delegation, and Harvard-grade codebase updates.
- **Ponytail Layer**: Student dev pack repository integration providing ~54% output-token reduction for cost-effective agent reasoning.

## SECTION 4: TERMINAL-CENTRIC THIN-CLIENT EXECUTION

### 4.1 Low-Power Chromebook Thin Terminal

Emmanuel operates from a low-power Chromebook. The local device carries zero heavy compute load and functions strictly as a thin terminal into the cloud environment.

### 4.2 Standalone AWS Linux Workspace VM

- **Execution Location**: Dedicated AWS Linux VM running in us-east-1 (maroon-tech).
- **Environment Provisioning**: Houses all developer tools, dependencies, runtimes, AWS CLI, VS Code Server, project workspace, and AI agent interfaces.
- **Workspace Storage Rule**: VM storage is temporary/workspace storage only. If destroyed, the entire environment is 100% rebuildable from the GitHub repository and documentation.
- **Daily Connection Workflow**:
  1. Open Chromebook.
  2. Authenticate via AWS IAM Identity Center SSO.
  3. Authenticate with GitHub.
  4. Launch VS Code / Terminal session into AWS Linux VM.
  5. Access maroon-technologies repository and resume work instantly.
