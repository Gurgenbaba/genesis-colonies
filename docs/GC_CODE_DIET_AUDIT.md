# GC Code Diet Audit

Read-only maintainability audit for Genesis Colonies. This is deliberately **not** a LOC-reduction refactor and does not change runtime behavior.

## Goals

- make physical LOC, non-blank LOC and comment-stripped SLOC reproducible
- separate runtime code from dev/CI scripts and tests
- rank the largest runtime files by SLOC
- surface exact AST-identical Python function-body candidates
- inventory explicit SQLite / legacy / deprecated / compatibility / fallback markers

## Commands

```bash
python tools/loc_report.py
python tools/code_diet_audit.py
python -m pytest tests/test_code_diet_audit.py -v
```

Both scripts emit a human-readable summary plus a machine-readable JSON line (`LOC_JSON=` / `CODE_DIET_JSON=`).

## Safety rules

The audit is advisory only.

- No file is deleted or rewritten by the audit.
- An exact duplicate body is a **candidate**, not proof that one copy may be removed.
- A marker hit is a **review location**, not proof that the compatibility path is obsolete.
- The audit intentionally makes **no dead-code claim**. Flask routes, Jinja references, dynamic imports, PJAX hooks and string-based dispatch make static reachability alone unsafe for deletion decisions.
- Runtime removals must be separate focused tickets/PRs with owner-specific tests and GC-000 checks.

## Recommended reduction order

1. Measure and baseline only.
2. Review exact duplicates with tests around the owning subsystem.
3. Review explicit compatibility/SQLite branches against the current PostgreSQL production path.
4. Split responsibility clusters only when behavior is already covered.
5. Treat `static/main.js` and `static/style.css` as consolidation projects, not bulk-deletion targets; dynamic DOM/CSS usage requires browser evidence before removal.

The KPI is not "lowest LOC". The KPI is less duplicated responsibility and fewer parallel/legacy paths while preserving the canonical system owners.
