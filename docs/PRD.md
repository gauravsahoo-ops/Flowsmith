# Flowsmith — Product Requirements Document (PRD)

> *This document is an alias. Please refer to the full primary specification:*
> **[PRODUCT_REQUIREMENTS_DOCUMENT.md](./PRODUCT_REQUIREMENTS_DOCUMENT.md)**

---

## Quick Reference Summary

- **Product**: Flowsmith Enterprise Workflow Automation Suite
- **Architecture**: Self-hosted, sovereign, distributed DAG execution engine
- **Frontend**: React 19, Vite 8, React Flow 12, Monaco Editor, Obsidian Glass design system
- **Backend**: FastAPI 0.115, Python 3.12, PostgreSQL 16 + pgvector, Redis 7
- **Key Modules**:
  1. Interactive Visual Workflow Canvas with Bezier routing & single-node execution
  2. Dual-queue execution engine (Redis + PostgreSQL fallback with worker recovery)
  3. Encrypted Credential Vault (AES-256-GCM + Fernet) with 1-click zero-config OAuth
  4. Native ReAct AI Agents & Tri-Tier Memory (Working, Summary, Episodic Vector)
  5. Native Relational Data Tables with schema builder and bulk CSV/JSON ingestion
  6. Human-in-the-Loop approval gates with tokenized links and auto-escalation
  7. 45+ first-party connectors including Salesforce & Microsoft Dynamics 365 Dataverse

*For complete functional specifications, non-functional requirements, and roadmap, see [PRODUCT_REQUIREMENTS_DOCUMENT.md](./PRODUCT_REQUIREMENTS_DOCUMENT.md).*
