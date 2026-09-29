# Ranking evaluation

Use frozen postings and independently recorded judgments to compare ranking changes. The evaluator makes no model calls, opens no browser and does not change the queue. It measures the automatic score cutoff; explicit pursue choices remain a separate product behavior.

Record a real development-set response in a new dataset copy. This command rejects
holdout IDs and existing labels, binds the judgment to the frozen posting hash,
and makes no model, browser or queue call:

```powershell
python -m joblazy record-judgment runtime/calibration/cases.json CASE_ID --output runtime/calibration/cases-labeled.json --decision worthwhile --quote "I would pursue this role." --basis "full description card"
```

When a newer full-description response corrects an older label, add
`--supersede` and use the prior labeled dataset as input. The command writes
another dataset version and retains the older judgment in `judgment_history`.

Run the fictional example:

```powershell
python -m joblazy evaluate examples/evaluation/cases.json --predictions examples/evaluation/predictions.json --output runtime/evaluation-example.json
```

For private work, keep the dataset, predictions and reports under `local/` or `runtime/`. Use `--minimum-score 60` to compare a different cutoff and `--top-k 10` to set the requested shortlist size. These options change only the report.

The dataset has `version: 1` and a `cases` list. Each case contains:

| Field | Meaning |
| --- | --- |
| `id` | Stable case identifier. |
| `job` | Frozen URL, employer, title, location and description. |
| `split` | `development` or `holdout`; their results are never pooled. |
| `category` | Sampling intent: `obvious_match`, `misleading_keywords`, `adjacent`, `seniority_stretch`, `internship`, `hard_constraint` or `other`. This is not a user fit judgment. |
| `judgment` | Optional `worthwhile` boolean, posting `job_hash`, and `source` with `kind: user`, exact `quote`, `recorded_at` and `basis`. Unlabeled cases stay unlabeled. |
| `known_block` | Optional independently reviewed exclusion: `policy_reason` plus a `source` containing `kind: reviewed_posting` and an exact posting quote. It must not be copied from the scorer being evaluated. |

Calculate content bindings with `joblazy.store.choice_job_hash(job)`. Whitespace and source bookkeeping do not change the binding; changed role content does. Stale judgments are reported and excluded from precision. Equivalent known posting/application URLs and duplicate content cannot appear in multiple cases, including across splits.

The predictions file has `version: 1`, a descriptive `name` and a `predictions` list. Each entry supplies the case `id`, `job_hash`, `profile_hash` and saved `assessment`. Keep failed or missing assessments visible; do not fabricate low scores for them. Reports expose missing predictions and differences in profile hashes or assessment versions, so mixed historical snapshots cannot masquerade as a controlled comparison.

Validated `experience_screen` exclusions are a distinct unscored assessment type. The evaluator checks the posting binding, exact requirement quote and numeric ceiling evidence, counts them in `eligibility_screened`, and treats them as not recommended without inventing a zero score. A user-labelled worthwhile role excluded by the screen remains visible among missed opportunities. Invalid screen records remain missing/invalid predictions; a deferred screen alone is not a completed assessment.

The report distinguishes:

- Available top recommendations from the requested top-k count.
- User-label coverage from recommendation precision. Precision remains null when any selected top role lacks a judgment. Reported bounds describe possible missing-label outcomes, not statistical confidence intervals.
- Worthwhile roles missed by the automatic cutoff from selected roles that the user rejected.
- Known policy violations from unknown or unextracted requirements. Zero recorded violations does not prove that all constraints were found.
- Development observations from reserved holdout cases that have not yet been assessed or judged.

Freeze a dataset before comparing runs. Use development cases for changes and reserve separate cases for evaluating those changes. Preserve every evaluation result; if an observed holdout failure later informs development, record that exposure and use a new reserved set for subsequent independent checks. Do not discard failures to improve reported precision.

A small, selected sample or judgments based only on brief role summaries remain provisional even when all available labels agree. Model agreement with itself is not a user-quality measurement. `example_only: true` marks fictional demonstrations explicitly.

For repeatability checks, freeze the task, serialized input, schema, model settings and candidate profile, then record their hashes for each fresh inference. Use separate private response-cache directories with an explicit shared request budget; replaying an existing cached response proves reuse, not model repeatability. Compare eligibility, fit category and the resulting selection decision alongside the numeric score. A small repeated sample cannot establish recommendation precision or population-wide stability.

Keep synthetic test provenance outside the evidence being measured whenever possible. Text such as “not a real vacancy” inside a job description can legitimately affect authenticity judgments and the overall score. Such a fixture can still test a specific condition, such as optional relocation, but its score is not a clean measure of real-job ranking stability. Preserve the original cases and record any confound; do not silently edit frozen evidence. Changing serialization order and generating a new response together also cannot isolate an ordering effect from ordinary generation variation.
