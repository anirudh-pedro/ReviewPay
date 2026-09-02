# RevivePay release baseline evidence

This is the approved comparison point for the `production-readiness-cleanup`
remediation. It records the verified pre-remediation state of the backend test
suite and the frontend checks so later release validation compares against
evidence rather than memory (Requirement 1.6).

The baseline is a floor, not an equality test. A later suite may report more
passing tests. A later suite may **not** report fewer unless a reviewed
replacement-coverage record in this document identifies the removed test, why it
was removed, and the coverage retained in its place (Requirement 1.7).

## Verified baseline

| Check | Result | Notes |
| --- | --- | --- |
| Backend test suite | 595 passing | Measured before any remediation work began. |
| Frontend TypeScript typecheck | pass | No type errors. |
| Frontend production build | pass | Vite production build completed. |

Repository revision at baseline: `ef05745d7d35a14182730a095df0c62f78b5d56d`.

At the time this record was written, the working tree at that revision still
contained required runtime source that Git does not track (the `app/models/`
package, the Razorpay integration, and the gateway route/schema). The Source
Tracking Guard reports those paths, and task 1.3 corrects the tracking. The
baseline numbers above were measured from that working tree, so they describe
the behavior under review, not a clean checkout.

## Baseline command forms

These are the supported command forms used to produce the baseline. They are
non-mutating: no dev server, no migration, no outbound provider or Copilot
request.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

## Later observations

Observations are evidence of the current suite size. They never replace the
approved baseline.

| Observation | Passing backend tests |
| --- | --- |
| After task 1.1 added Source Tracking Guard coverage | 601 |
| After task 1.2 added cleanup-inventory and release-input coverage | 687 |

## Machine-readable baseline record

The release-input report reads the fenced block below. Keep it consistent with
the table above; `scripts/release_inputs.py` rejects a record that claims a
baseline weaker than the approved 595.

<!-- revivepay:baseline-evidence -->

```json
{
  "schema_version": 1,
  "recorded_at": "2026-09-02",
  "repository_revision": "ef05745d7d35a14182730a095df0c62f78b5d56d",
  "baseline_passing_backend_tests": 595,
  "frontend_typecheck": "pass",
  "frontend_production_build": "pass",
  "commands": {
    "backend_tests": ".\\.venv\\Scripts\\python.exe -m pytest -q",
    "frontend_typecheck": "npm --prefix frontend run typecheck",
    "frontend_build": "npm --prefix frontend run build"
  },
  "observations": [
    { "label": "after task 1.1 source tracking guard coverage", "passing_backend_tests": 601 },
    { "label": "after task 1.2 release input coverage", "passing_backend_tests": 687 }
  ],
  "notes": [
    "Baseline measured from the working tree at the recorded revision, which still contained untracked required runtime source.",
    "Task 1.3 corrects repository tracking for every Source Tracking Guard finding."
  ]
}
```

## Reviewed replacement coverage

A replacement-coverage record is the only accepted justification for a backend
test count below the baseline. Each record justifies exactly one removed test and
must identify the removed test, the removal reason, the retained coverage, the
reviewer, and the review date. Incomplete records are rejected, and a rejected
record justifies nothing.

No test has been removed, so the reviewed set is empty.

<!-- revivepay:replacement-coverage -->

```json
[]
```

Record shape, for reference when a removal is proposed:

```text
{
  "removed_test": "tests/test_example.py::test_case",
  "removal_reason": "why the test no longer describes supported behavior",
  "retained_coverage": ["tests/test_other.py::test_equivalent_case"],
  "reviewer": "reviewer identity",
  "reviewed_at": "YYYY-MM-DD"
}
```

## Commands

```powershell
# Validate the release inputs (tracking, baseline, replacement coverage, inventory).
.\.venv\Scripts\python.exe -m scripts.release_inputs --passing-tests 687
```

Both commands in this document are read-only. Neither is an Operational
Mutation: they change no payment, recovery, policy, clock, job, outbox, scenario,
or demo state.
