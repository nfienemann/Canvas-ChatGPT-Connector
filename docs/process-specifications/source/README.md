# CanvasBridge — 17 Engineering Process Specifications

This package contains **17 standalone, implementation-oriented Markdown specifications**, plus an implementation roadmap and dependency matrix. They target process gaps around evidence quality, change propagation, state recovery, cross-source identity, data rights, learner workflows, and production reliability.

They are **proposals**, not a representation that the current codebase already contains the named objects or APIs. Before coding, inspect the repository and reconcile each proposed interface with its actual architecture, tests and existing compliance specifications.

## Non-negotiable architectural constraints
- Independent local/imported academic intelligence must continue to function without institutional Canvas/LMS access.
- Restricted LMS adapters must remain blocked until actual authorization requirements are satisfied, including any provider approval.
- The **existing/in-progress Academic Integrity spec** is a dependency and is **not rewritten** here.
- Generated answers and plans must not be treated as official institutional determinations.
- No autonomous outward write, assignment submission, communications, or publication.

## Files
- `specs/CB-01-*.md` — Academic Evidence Reconciliation & Conflict Resolution
- `specs/CB-02-*.md` — Academic Change Impact Engine
- `specs/CB-03-*.md` — Evidence Sufficiency & Uncertainty Protocol
- `specs/CB-04-*.md` — Academic State Recovery & Dependency Invalidation
- `specs/CB-05-*.md` — Cross-Provider Academic Identity & Migration
- `specs/CB-06-*.md` — Revocation, Data Lineage & Derived Artifact Retention
- `specs/CB-07-*.md` — Assignment Lifecycle & Completion State Machine
- `specs/CB-08-*.md` — Cross-Course Knowledge Graph & Competency Evidence
- `specs/CB-09-*.md` — Workload Feasibility & Contingency Simulation
- `specs/CB-10-*.md` — Degree Progress & Prerequisite Dependency Analysis
- `specs/CB-11-*.md` — Instructor Clarification & Escalation Workflow
- `specs/CB-12-*.md` — Prompt-Injection & Document Trust Boundaries
- `specs/CB-13-*.md` — Upgrade, Migration & Downgrade Recovery
- `specs/CB-14-*.md` — Evaluation & Regression Testing Framework
- `specs/CB-15-*.md` — Student Data Correction, Deletion & Export
- `specs/CB-16-*.md` — Privacy-Safe Failure Diagnosis & Support Reporting
- `specs/CB-17-*.md` — Portfolio Publication Clearance & Attribution

See `IMPLEMENTATION_ROADMAP.md` and `DEPENDENCY_MATRIX.md` for sequencing and integration.
