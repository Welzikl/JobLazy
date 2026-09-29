# Why JobLazy uses this foundation

## What stopped the old workflow

The original project had useful individual components, but its connected application path was much narrower than its discovery and CV-generation capabilities.

- The saved ten-role trial produced ten one-page CVs but no field fills, uploads or submissions. The failures occurred after useful preparation work had already been done.
- A reproduced integration defect let the application-pack builder produce a `local/application-profile.json` source reference that its downstream evidence verifier rejected because it expected a confirmed-answer record.
- The Ashby preparation path rejected extra/manual controls, including optional ones. Greenhouse filling/upload was explicitly disabled, and Workday intake was unsupported.
- Earlier unsupported queue items could consume the next batch's capacity repeatedly.
- Ranking and rewriting depended on an active agent supplying reviewed payloads; the guarded workflow did not itself invoke a model to perform those steps.

These were integration and coverage problems. Adding more prompts or another agent framework would not by itself repair them.

## Reuse choice

| Source | Useful part | Decision |
| --- | --- | --- |
| [Personal-JobPilot](https://github.com/TheCromazone/Personal-JobPilot) | Semantic scanner, React-aware filler and deterministic field mapper | Reuse the MIT components at a pinned commit. Replace author-specific defaults and outcome assumptions at the integration boundary. |
| Existing Career Ops adaptation | Broad ATS/feed providers, deterministic HTML renderer and selected CV template | Keep these as small Node tools. Preserve original files and private history. |
| [ai-job-agent](https://github.com/AkbarDevop/ai-job-agent) | Modular ATS scripts and agent-driven workflow | Useful reference, but not a substitute for a verified unattended pipeline. |
| [job-application-agent](https://github.com/torontodeveloper/job-application-agent) | Small profile-to-form implementation | Reference only: no declared repository license was established in the audit, and its completion marker did not establish confirmed submission. |
| [job-agent](https://github.com/lordvacuum/job-agent) | Cheap preflight and explicit uncertain outcomes | Reference only: no declared repository license was established. |
| [ats-scrapers](https://github.com/kalil0321/ats-scrapers/tree/6b44a1badc9bfbf5cf176f75265cc5729e520e99) | Uber catalogue parser and pagination checks | Source and MIT license reviewed during the Uber coverage audit. Not integrated or copied into public source. Its Uber implementation requires an additional transport dependency; JobLazy's ordinary browser probe received HTTP 403. The existing Muse provider supplies a working targeted discovery path. |

The GitHub projects were code-reviewed; their public usage claims were not independently verified. JobLazy's status document distinguishes what has actually run here.

## Deliberate simplifications

- One Python process and SQLite queue coordinate the work.
- Two Node operations retain tested discovery/rendering components instead of rewriting them.
- Codex account login supplies a configurable lower-cost model. No Ollama, local model downloads, paid API fallback, Hermes service, dashboard backend, mail integration or outreach agent is required.
- Full descriptions are retrieved before fit decisions. Cheap title/location signals prioritize processing without acting as the final ranking.
- Cached structured model results, scoped saved answers, file hashes and durable outcomes connect the stages.
- Existing private data is migrated mechanically; unknown facts remain unknown.
- Source snapshots carry their original licenses and content hashes. Inactive upstream application code is not shipped.

## What remains a hypothesis

The first real-model checks and local form tests are promising, but they do not prove all-day reliability, broad ATS coverage or fully autonomous applications. Those require supervised live preparation, more form variants, outcome validation and then continuous-operation testing. The goal remains active until that larger behavior is established.

## Ranking comparison with the donor, verified 2026-09-14

Career Ops already has scoring. JobLazy reused discovery and rendering components but implemented its own structured assessment; it did not port the original scoring rubric intact. This distinction must be explicit when describing reuse.

| Component | Observed behavior | Reuse decision |
| --- | --- | --- |
| Donor `rank-pipeline.mjs` | Optional batch annotations on pending Markdown rows, capped requests, score out of five and a short reason. The prompt supplies company, title, URL and the first 2,000 CV characters; the script does not itself retrieve full job descriptions. | Useful cheap prioritization pattern, insufficient as the final full-description evaluator. Do not add a second runtime scorer merely to duplicate existing ranking. |
| Donor `modes/_shared.md` and `modes/oferta.md` | Agent-run assessment of CV fit, career direction, compensation, culture and red flags, with a global 1–5 judgment and detailed requirement/report sections. Posting legitimacy is separate. | Recover the named decision dimensions in the existing assessment/report path, retaining current evidence checks. This is the useful original rubric, distinct from the lightweight pipeline script. |
| JobLazy `joblazy/materials.py` at the initial comparison, before version 4 | Full description and canonical facts; validated quotes and source IDs; requirement statuses; separate eligibility and fit category; overall 0–100 judgment. Deterministic experience-ceiling enforcement. | Preserve the factual and eligibility controls. Career direction and compensation are supplied through targeting, but separate dimension verdicts are not enforced in the output schema. |

The donor is not internally uniform: `_shared.md` specifies a holistic global judgment with no arithmetic formula, while `oferta.md`'s tracker instruction defaults to an average of block scores unless overridden. The public methodology component describes 4.0 as its recommendation boundary, while `_shared.md` permits 3.5–3.9 with a specific reason. These are reasons to choose one documented interpretation, not evidence that the original system was incapable of ranking.

JobLazy's configured 70-point threshold is not a calibrated conversion of the donor's five-point scale. Do not equate 70/100 with an original recommendation category, change it to 80 merely by arithmetic, or re-rank all existing applications to make the scales appear aligned. First reuse the named rubric within the current evaluator and compare a fixed development set plus separate held-out user judgments. Preserve existing scores as historical observations.

The user has supplied positive interest judgments on five named strategy, operations and growth recommendations. These are saved privately with the exact assessments and job snapshots as development feedback. They establish interest in those five roles, not broad recommendation precision, eligibility, current availability or a held-out quality result. No scoring engine or threshold was changed during the initial source comparison.

Subsequent implementation: assessment version 4 now uses these five named dimensions within the existing evaluator and review renderer. It follows the shared rubric's holistic aggregation interpretation; the existing overall scale and threshold are retained pending calibration. A bounded fixed-posting trial found one user-interest/cutoff disagreement and one quote requiring source correction. See `STATUS.md` for the actual evidence and limitations; this does not establish equivalence to the original agent-run evaluation or calibrated quality.
