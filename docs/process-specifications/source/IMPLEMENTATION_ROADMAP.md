# CanvasBridge: 17-Spec Implementation Roadmap

**Purpose:** stage these proposals without breaking the independent academic-intelligence/local-import architecture or the separately developing academic-integrity policy engine.

## Suggested delivery order

**Stage 0 — Prerequisites:** inventory existing data models, authorization registry, local document store, academic integrity interface and current tests. Establish baseline regression fixtures. Do not turn on restricted institutional connectors without validated authorization.

**Stage 1 — Trust and evidence:** CB-12 (prompt-injection boundaries), CB-03 (evidence sufficiency), CB-01 (contradictions), CB-14 (evaluation). These establish safe inputs and measurable correctness.

**Stage 2 — State and provenance:** CB-06 (revocation/lineage), CB-04 (recovery), CB-05 (identity reconciliation), CB-13 (migration), CB-15 (correction/export). This creates reliable state lifecycle and recovery.

**Stage 3 — Student workflow:** CB-07 (assignment lifecycle), CB-02 (change impact), CB-09 (feasibility), CB-11 (clarification). Start with read-only proposals.

**Stage 4 — Higher-order intelligence:** CB-08 (cross-course knowledge), CB-10 (degree progress), CB-17 (portfolio clearance). Roll out only with robust source-quality and rights provenance.

**Stage 5 — Support hardening (build incrementally from Stage 1):** CB-16 diagnostic reporting and operational QA.

## Release gates
- Critical policy, privacy, and prompt-injection regressions: zero allowable known high-severity failures.
- No release allows a restricted connector to become usable through local-import pathways or derived caches.
- Data migrations tested with backups, partially corrupted data and interrupted executions.
- All outward-facing write operations have explicit preview, permission and user action.
- Uncertain answers clearly expose missing/contradictory evidence.

## Integration with the separately developed academic-integrity specification
These 17 docs intentionally do not define a replacement policy engine. They depend on its authoritative policy-decision API. CB-03 supplies evidence-completeness signals; CB-07 supplies action classification and assignment context; CB-12 protects policy inputs; CB-06 handles permitted retention; CB-14 tests policy outcomes. Keep fail-closed behavior for explicitly prohibited work and missing/ambiguous-policy behavior aligned with the existing integrity design.
