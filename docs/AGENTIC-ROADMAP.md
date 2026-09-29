# JobLazy: goals for reliable autonomy

Proposed goals, in execution order. These are acceptance criteria for future work, not claims that the behavior exists or authorization to submit applications. This historical roadmap does not set the current preparation authorization. Read the saved private preparation policy and [current status](STATUS.md) before acting. Engineering and fictional fixtures may continue; real preparation resumes only when the user requests it.

## 1. Make the selected batch resumable from one answer inbox

**Goal prompt:** Complete the selected batch's answer-to-form workflow. Use the existing verified CVs and open application sessions. Collect missing facts once, record their user provenance and intended scope, and apply confirmed answers to the correct forms. Make it possible to save or correct an answer while an application remains under manual review and explicitly resume that same owned session. Stop before Submit. Do not recreate the shortlist, regenerate unchanged CVs, silently release manual ownership, or close the user's review tabs.

Build on `answers.py`, `assist.py`, `inspection.py`, `profiles.py` and `checkpoints.py`; replace the private batch wrapper with a supported path only where needed. The original private wrapper could not apply new answers to its open pages. Supported same-document resumption now works in connected local checks, including preservation of operator edits and verified attachments. Consistency across real employer forms remains unproven and any real preparation follows the current user authorization.

Completion evidence:

- Confirmed contact facts and answer corrections survive restart and become available through the normal profile/answer workflow. An answer is not complete merely because it exists in an unrelated sidecar file.
- A single review list groups equivalent questions while preserving exact employer wording, choices, job IDs and answer scopes. Similar wording alone must not imply equivalent consent.
- Saving ordinary application answers preserves valid CV work. Where source changes actually alter the CV, invalidate only dependencies whose inputs changed; do not disable checkpoint verification to avoid regeneration.
- Resume rechecks the current form and values, preserves user edits or reports conflicts, and does not repeat a verified attachment unnecessarily.
- On a fictional connected form, a new answer supplied during a live handoff appears in that same page without another model request or CV generation. Unknown submission outcomes remain protected.
- On the selected real applications, resolve every question supported by confirmed facts. Produce an exact remaining-input list for the others, separating login, eligibility, user commitments, missing experience and software defects.
- Demonstrate at least five selected applications ready for final human review if their required user inputs are available. If inputs prevent that count, report the dependency rather than treating the entire goal as complete.

## 2. Turn observed employer failures into measured ATS coverage

**Goal prompt:** Make browser preparation reliable for the ATS variants used by worthwhile selected roles. Reproduce each actual failure with a minimal local fixture, fix its cause, then recheck the affected approved live application. Keep role quality independent of form convenience. Do not resubmit, fabricate inputs, or treat an attached filename as proof of employer-side receipt.

Completion evidence:

- A compatibility matrix distinguishes public discovery, navigation, scan, fill, attachment, later steps and final-review readiness for each ATS actually exercised.
- Local connected cases cover Ashby, Greenhouse, Lever and any additional platform encountered in selected roles. Label fixture support separately from live success; the current live batch is Ashby-heavy.
- Every live attempt records exact artifact hash, actual field-value checks, attachment evidence, current step, missing answers and failure reason.
- Native file selection, successful upload transport and employer-side persistence are separate evidence levels. Do not upgrade one into another.
- Missing answers pause only their application. An unsupported control does not prevent already supported fields from being prepared where partial preparation is appropriate.
- Repeated technical failures leave the normal queue after a bounded retry count. No silent restart of a manual handoff or uncertain application.

## 3. Make shortlist decisions reflect the user's preferences

**Goal prompt:** Calibrate JobLazy's role ranking and CV quality against user judgments. Use the current canonical profile, full job descriptions and broad discovery sources. Record accept/reject reasons, improve the ranking policy, and evaluate on roles withheld from the adjustment process. Keep the runtime on a verified lower-cost Codex model with no silent provider or Astra fallback.

Completion evidence:

- Obtain user labels for at least 20 varied roles, including clear matches, rejected sectors, internships, seniority stretches and adjacent functions. These labels are a real user dependency.
- Keep a separate evaluation set of at least 20 roles. Record precision among recommended roles, hard-constraint violations and common disagreement reasons before and after changes.
- Proposed target: at least 80% user-accepted recommendations and zero known hard-constraint violations in that evaluation set. Report small-sample limits; a model's own fit score is not a user label.
- Internship eligibility, seniority and work authorization remain explicit when unresolved. No convenient ATS preference may substitute for fit.
- Audit a sample of at least ten tailored CVs for factual support, emphasis, readability and PDF layout. Unsupported claims fail the gate rather than becoming profile facts.
- Report actual request counts, input/output usage, cache reuse and wall time. Only compare runtime models on the same evaluation cases and verified account availability.

## 4. Prove continuous operation before adding startup automation

**Goal prompt:** Run a bounded 24-hour continuous-operation trial that discovers, deduplicates, ranks, tailors and prepares only applications within an explicitly saved preparation policy. Use the existing Codex login and chosen cheaper model. Persist progress, respect daily limits, sleep while idle, and surface only meaningful new results or exceptions. Keep final submission disabled for this trial.

Prerequisites: Goals 1 and 2 establish a working application workflow; the user supplies targeting, preparation scope and usage limits. Choosing a notification destination does not itself authorize sending messages.

Completion evidence:

- One actual 24-hour trial with start/end timestamps, observed process status, queue/event history, request usage and per-role outcomes. A two-cycle fixture is not an overnight run.
- Controlled stop/restart, expired login, provider outage, network failure, duplicate discovery and daily-limit reset preserve intended state without duplicate applications.
- Manual sessions are never reclaimed automatically. Uncertain outcomes remain paused until verified.
- No model requests occur merely to check an empty queue. Requests are reserved before dispatch and stay within the saved policy.
- Publish a private daily report of useful outcomes and exceptions, not repeated unchanged status messages.
- After the trial passes, add opt-in Windows startup with a documented stop/disable path and verify restart behavior on the actual host.

## 5. Add narrowly scoped autonomous submission

**Goal prompt:** After supervised preparation and outcome checks pass, implement opt-in final submission under a user-approved policy. Limit authority to explicitly permitted jobs, destinations, daily volume, candidate facts and commitments. First prove the policy and outcome handling locally, then carry out a separately authorized small live pilot. Never infer submission success from a disappearing form or redirect.

This goal changes the current stop-before-Submit boundary and needs explicit authorization before any real submission. Past preparation or upload approval does not grant it; preparation is currently paused.

Completion evidence:

- A readable policy defines job eligibility, exclusions, allowed answers, salary/location/availability limits, artifact requirements, expiry and a submission cap. Ambiguity routes to the user.
- Persist submission intent before the action. Scope success to a new application-specific employer receipt or a separately labeled user report.
- Inject failures immediately before, during and after submission. Every ambiguous result remains protected against automatic retry.
- A live pilot of no more than three separately approved applications records each actual receipt or unresolved outcome. Never force the target count through an ambiguous application.
- Resume after process interruption without a duplicate submission. Demonstrate an immediate stop mechanism and audit trail.
- Expand only within a subsequent explicit policy. Rejections or interviews can inform fit preferences; they cannot create employment claims or establish causality from a tiny sample.

## 6. Ship the MIT project another person can run

**Goal prompt:** Package the stabilized JobLazy workflow as a clean MIT project. Preserve upstream notices and source hashes, keep candidate data and browser sessions private, and verify setup from the exact source artifact in a fresh environment. Publish to the intended GitHub repository only when publication is authorized.

Completion evidence:

- Source-only installation using pinned dependencies and documented Python, Node, browser and Codex requirements.
- Fictional onboarding examples, a connected local demo, CLI help and a short operations guide for discovery, preparation, answers, review, restart and outcome reconciliation.
- A public-data audit covering tracked files and the actual release artifact, plus retained upstream license/hash verification.
- Tests execute from the exact extracted release artifact. Record its commit and SHA-256; distinguish later checkout changes from the release.
- Document supported platforms, unverified ATS behavior, account limits and submission defaults candidly.
- Verify repository visibility, license, release contents and absence of candidate/browser/credential data after authorized publication.

## Execution discipline

Choose the next unmet acceptance criterion and work toward its observable result. After fixing a reproduced failure and passing its relevant checks, return to the user workflow. Do not repeatedly repackage unchanged source, broaden unrelated tests, add speculative adapters or create more CVs to substitute for finishing the selected applications. Preserve a live process handle during a running operation. If user input is the only remaining dependency, record it precisely and stop spending model requests on that dependency.

Current priority while preparation is paused: improve and evaluate ranking usefulness, expand measured discovery gaps, and fix observed preparation failures through fictional fixtures. Resume the real verification in Goals 1 and 2 only after the user requests preparation again. See [current status](STATUS.md) for evidence and outstanding dependencies.

