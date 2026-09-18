# Golden Tests — Frozen Ground Truth

Hand-verified expectations for the safety-critical path. Per the project workflow:

- These cases may be ADDED to. They must not be edited or deleted without explicit
  human approval, and never "regenerated" from current behaviour. A golden test that
  is rewritten to match the code it is meant to check has stopped being a test.
- Every entry in `BUGLOG.md` has a permanent case here. A fix without its regression
  case is not a fix, it is a bug that has gone quiet.
- Expected values are derived by hand or from first principles in the docstring of
  each case, not captured from a previous run of this software.

Run with:

    cd backend && pytest tests/golden -v
