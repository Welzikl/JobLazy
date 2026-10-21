# JobLazy capabilities

Reviewed 21 October 2026 for 0.1.0-rc.3. Start with the [main page](../README.md) or [use-case casebook](USE-CASES.md). This inventory describes the implementation; it does not certify broad live-site reliability.

## Ways to use it

| Mode | How it works | Requirements and evidence |
| --- | --- | --- |
| Codex chat | The shared skill operates the existing local pipeline through `AgentModel`, using the current chat for model responses. | Local helpers and host web/browser tools. A fictional intake exchange was exercised in a real Codex chat. |
| Claude Code chat | The Claude skill entrypoint reads the same shared workflow and uses the same bridge. | No Codex inference subprocess or second login in chat mode. A live Claude Code session is untested. |
| Optional dashboard | A local browser UI uses the existing Codex CLI backend and configurable model; the Windows friend launcher uses its Luna preset. | Separate Codex setup. Historical live/fixture evidence is in [STATUS.md](STATUS.md). |

## Built-in workflow

| Capability | What it does | Implementation / practical limit |
| --- | --- | --- |
| CV intake and confirmation | Extract PDF, DOCX or text into a draft, ask follow-ups and save a confirmed profile. | [onboarding.py](../joblazy/onboarding.py); readable source text required. |
| Preferences and corrections | Keep desired work/location separate from career evidence; preserve confirmed facts during profile edits. | [profile_edit.py](../joblazy/profile_edit.py); new users supply their own facts and preferences. |
| Discovery | Read supported public ATS postings and feeds. Chat uses its available web tools for six complementary search passes. | [search.py](../joblazy/search.py), [ATS reader](../joblazy/ats_postings.py), [shared skill](../skills/joblazy/SKILL.md); partial market coverage. |
| Dashboard search orchestration | Review a search plan; run six complementary model missions with at most three concurrent workers. | [search_coordinator.py](../joblazy/search_coordinator.py), [search_missions.py](../joblazy/search_missions.py); chat mode does not require six agents or a named model. |
| Deduplication and saved results | Use posting identities, verified aliases, source caches and evidence-bound response reuse. | [store.py](../joblazy/store.py), [search.py](../joblazy/search.py); saved vacancies still need freshness checks. |
| Job ratings and full assessment | The original Career Ops rubric gives an overall 0–100 score, Strong match / Worthwhile stretch / Poor fit, and five 1–5-or-Unknown ratings: CV fit, career direction, compensation, culture/working conditions and red flags. Chat and batch assessment reuse the same evidence contract. | [materials.py](../joblazy/materials.py), [shortlist_review.py](../joblazy/shortlist_review.py), [rating tests](../tests/test_rubric.py); overall score is holistic, not an average or hiring probability. |
| Selection and eligibility | Default profile cutoff is 70/100; an explicit choice can pursue a worthwhile stretch below it. Known hard constraints and Poor fit still block selection. Unknown eligibility remains visible. | [pipeline.py](../joblazy/pipeline.py), [search_review.py](../joblazy/search_review.py); search leads and retrieval failures are not scored as poor candidates. |
| Tailored CVs | Generate for chosen roles, check claims, render the existing template and validate the PDF. | [materials.py](../joblazy/materials.py); user and visual review remain necessary. |
| Exact-file review | Bind review and preparation to the CV artifact's SHA-256. | [checkpoints.py](../joblazy/checkpoints.py); changed files need fresh review. |
| Assisted form preparation | Fill supported confirmed fields and attach the reviewed CV in a visible browser. | [assist.py](../joblazy/assist.py); host must keep the interactive browser/process alive. Final Submit is manual. |
| Answers and continuation | Save explicit answers and resume the current live form session. | [assist_bridge.py](../joblazy/assist_bridge.py), [application_ui.py](../joblazy/application_ui.py); missing sensitive facts require the user. |
| Outcomes and tracker | Persist job states and recorded outcomes; export the canonical SQLite tracker as CSV. | [store.py](../joblazy/store.py), [dashboard.py](../joblazy/dashboard.py), [agent.py](../joblazy/agent.py); CSV is a snapshot and no mailbox synchronization is provided. |
| Local safeguards and packaging | Exclude private runtime/profile data; retain vendor hashes and notices. Dashboard has loopback, token and origin protections. | [release builder](../scripts/build-release.py), [source audit](../scripts/check-public.py); not a general security certification. |

Local processing/request limits protect helper operations. They are not a measurement of all host-chat tokens, a subscription allowance, or a promise of completed applications. See [operations](OPERATIONS.md).

## Work done with the accompanying agent

Exact historical CV retrieval, interview briefs, company/territory research, outreach drafts, questionnaire copies and portfolio decks are described in the [casebook](USE-CASES.md). The agent can work from saved artifacts and user-provided evidence; those tasks are **not dedicated JobLazy modules**. Document creation and research depend on tools available in the host. Sending messages requires the user's instruction.

## Verification and exclusions

The [rc.3 verification report](AGENT-VERIFICATION.md) records 546 passing tests from a fresh Windows extraction, the fictional Codex intake exchange, source/privacy checks and their limits. The [status page](STATUS.md) preserves separate historical dashboard/live-model evidence and the unresolved receipt-observation issue. Live Claude Code operation and a new user's hardware/account remain untested.

Automatic employer submission, automatic email reconciliation, automatic outreach and a guaranteed daily application count are not provided. No test count establishes hiring outcomes.
