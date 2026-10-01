# Worked examples

These are hypothetical development tasks, not claims about deployed JJAI systems.
The contracts illustrate the method. No scenario's acceptance checks have been
executed as part of authoring this package.

## 1. Implement a duplicate-safe document webhook in staging

**Request:** Build a staging webhook handler. A valid signed event creates one
processing job, duplicate events must not create another job, and invalid
signatures must be rejected. Do not deploy to production or send client messages.
The staging harness supplies synthetic fixtures and two tenant identities.

**Outcome:** A staging-verified handler that creates one correctly scoped job per
valid event, rejects invalid requests, and remains duplicate-safe during retries.

**Scope:** Handler, validation, job persistence, tests, and developer handover.
OCR processing itself, production deployment, and external messages are excluded.

| ID | Mandatory condition | Verification | Evidence |
|---|---|---|---|
| C1 | A valid signed fixture creates the expected job for its tenant. | Invoke the handler in staging and inspect the persisted row. | Request/response plus row identity tied to the final code revision. |
| C2 | Replaying the same valid event produces no additional job. | Replay it sequentially and concurrently; count matching jobs. | Test output and database readback showing exactly one job. |
| C3 | Invalid or absent signatures create no job. | Negative fixtures; inspect both response and absence of writes. | Rejection responses and scoped database readback. |
| C4 | One tenant cannot create or retrieve another tenant's job. | Cross-tenant fixture and boundary test. | Actual test result against the final staging candidate. |
| C5 | Failed writes produce a failure response, not a false success. | Inject a persistence failure and verify the failure path. | Failure-injection test result. |
| C6 | The delivered revision passes these checks and relevant existing regressions. | Run the applicable suite after the final edit; review the diff. | Revision ID, commands, output, and concise handover instructions. |

**Stopping:** DONE only after C1–C6 and the scope constraints pass. Missing staging
access means BLOCKED, not DONE. A local mock pass cannot substitute for the
requested staging result. If the user accepts a tested-local deliverable instead,
record an authorized revision; do not silently lower the level.

**No-progress rule:** Apply the runtime's approved retry budget. A repeat requires
new evidence or a changed repair hypothesis. Do not invent a previously agreed
numeric budget.

## 2. Compare retrieval designs for a document assistant

**Request:** Produce a decision memo comparing exact/keyword, vector, and hybrid
retrieval for our document assistant. Assess source support, limitations, tenant
filtering, and evaluation cost. Do not build or deploy the system.

**Outcome:** A reviewable decision memo that supports a design choice while
separating verified documentation, reasoned tradeoffs, and untested performance.

| ID | Mandatory condition | Verification | Evidence |
|---|---|---|---|
| C1 | All three approaches are compared on the requested dimensions. | Coverage matrix against the request. | Corresponding memo sections. |
| C2 | Material product-specific claims are supported by accessible primary sources. | Open the cited sources and inspect support for each claim. | Claim-to-source map with access dates. |
| C3 | Benchmarked results are not claimed unless actually measured. | Review all numeric performance/cost statements and their provenance. | Explicit measured/estimated/unknown labels. |
| C4 | Recommendation states assumptions, tradeoffs, unresolved gaps, and what would change the decision. | Apply a rubric covering those four elements. | Recommendation and limitations sections. |
| C5 | Memo is delivered in the requested form, without implementing the system. | Inspect the artifact and action record. | Memo reference and scope statement. |

**Stopping:** Once coverage and source checks are satisfied, deliver. Do not keep
researching simply because more articles exist. If a required product fact cannot
be established, report that gap and whether it blocks the recommendation. Never
claim search exhaustiveness or production validation.

**Important distinction:** An unknown performance result can be acceptable in a
research memo explicitly scoped to documentary comparison. It is not acceptable
in a contract promising measured performance.

## 3. Build an SOP-to-skill pipeline for development use

**Request:** Build a local development workflow that converts approved SOPs into
candidate skills. A changed SOP should produce a new candidate, not automatically
replace an approved skill. Show source/version links, a review step, and tests.
Do not run this against a client's production environment.

**Outcome:** A tested-local prototype that converts supplied synthetic SOPs into
traceable candidate skills while preserving the approval boundary.

| ID | Mandatory condition | Verification | Evidence |
|---|---|---|---|
| C1 | An approved source fixture yields a candidate skill linked to the exact source version. | Execute fixture A and inspect candidate metadata. | Output files and source/version mapping. |
| C2 | An unapproved source cannot enter the approved skill collection. | Negative test using an unapproved fixture. | Rejection or quarantine result and unchanged approved collection. |
| C3 | A source revision produces a new candidate and preserves the prior approved skill. | Execute a changed fixture and compare before/after state. | Version/diff records and retained original artifact. |
| C4 | Publishing a candidate requires the designated local approval mechanism. | Try with missing and invalid approval, then valid approval. | Gate tests and resulting state transitions. |
| C5 | End-to-end output is readable and references only resources actually present. | Parse metadata, resolve file references, and inspect a representative output. | Validation output plus reviewer rubric. |
| C6 | Handover contains local setup, test procedure, known limitations, and no production claims. | Follow the documented local path and audit the claims. | Final artifact, test record, and README. |

**Stopping:** An implemented review queue is not evidence that a real client
approved a procedure. This task completes at tested-local prototype maturity.
Client deployment and client business execution remain excluded.

## Verification traps

- All workers passing does not prove their combined workflow works.
- A screenshot of a success message does not necessarily prove persisted state.
- An artifact hash proves which file was checked, not that its content is correct.
- A source link without source inspection does not establish support.
- An unavailable test is UNKNOWN, not PASS and not NOT_APPLICABLE.
- A worker cannot turn "deployed" into "deployment plan prepared" after it loses access.
- Optional polish is not an excuse to keep a completed task running.
