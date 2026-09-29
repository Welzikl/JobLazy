# Economical usage

The friend launcher uses GPT-6 Luna for every AI stage. There is no Astra fallback, API-key requirement or automatic credit purchase. The personal preset remains available separately.

## Local limits and account limits

JobLazy enforces at most **25 processing attempts** and **50 uncached model-request reservations per UTC day** across its normal runtime paths, including assisted preparation and resume. A processing attempt can be a preliminary review, full assessment or material-preparation operation; it is not a completed application. Failed uncached requests can consume reservations. A new day resets the local allowance.

These are local safeguards, not a translation of a roughly 20-per-month subscription into guaranteed capacity. Actual Codex usage depends on workload, context, reasoning and tools, and is shared with other Codex work. Check the account's own model access and usage/reset display. JobLazy does not currently read reliable remaining account capacity. [Official pricing and usage information](https://learn.chatgpt.com/docs/pricing).

## What saves work

| Stage | Implemented behavior |
| --- | --- |
| Public retrieval | Direct ATS reads, source caches, deterministic filtering and deduplication avoid model calls for routine collection. |
| New web discovery | Six complementary Luna missions, up to three concurrent model workers, bounded query/result budgets. Page refresh and saved-result views do not start new searches. |
| Interrupted searches | Explicit resume reuses completed missions and continues missing work. |
| Preliminary shortlist | A compact batch shares the candidate evidence across a small selected set of verified roles. |
| Full assessment | Only selected roles are assessed from the application screen; current complete validated results can be reused. |
| Materials | Generated only after selection. Reusable checkpoints bind the CV to the role and confirmed profile; reviewed hashes prevent silent replacement. |
| Form work | Ordinary code fills confirmed fields and renders PDFs. Confirmed answers and the current attachment survive live resume. |
| Limits | Shared atomic reservations prevent parallel workers from each receiving separate local allowances. Exhaustion stops work without a model upgrade. |

Concurrency can reduce elapsed time; it does not create extra account allowance. Keep the first trial small: one intake, one six-mission search with a small review batch, then one selected assessment and preparation. Measure elapsed time, recorded requests, cache hits and whether recommendations are useful before increasing volume.

Saved jobs and materials survive allowance errors. A still-open employer session may resume explicitly after capacity returns; closed sessions require a checked outcome before a new preparation attempt. Never blindly retry an uncertain submission.

## Not yet established

Live Luna-only recommendation/CV quality, the friend's available account capacity, a reliable number of applications per day, automatic account reset discovery and adjustable application headroom remain unproven or unimplemented. A cheap subscription alone does not establish any of them.

## Bounded live observation

On the development account, one fictional intake, plan, six-mission search and review, selected full assessment and CV generation used 12 uncached request reservations and five processing attempts. The search returned one stretch recommendation from three verified postings. A later factual wording correction required a separate bounded regeneration check. This is observed local usage, not an estimate of the friend's subscription capacity or daily successful applications.
