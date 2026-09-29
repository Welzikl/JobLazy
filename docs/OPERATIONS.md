# Advanced operations guide

For normal Windows friend use, follow [the quickstart](WINDOWS-QUICKSTART.md). This reference documents the optional command-line engine and historical verification. Commands without explicit model options retain personal defaults; the friend launcher selects Luna throughout. Current release evidence is in [status](STATUS.md).

An early working prototype built from reusable MIT components. Real Codex/Terra ranking and CV tailoring work with the saved profile. A supervised employer preparation trial exposed missing answers and location-selection defects; consistent live preparation and continuous operation remain unproven. Submission is tested against fictional local forms and remains disabled for real employers. There is no local model requirement.

Public posting reads now require one matching structured job title or primary page title before using the content or its advertised deadline. Formatting differences and an exact employer prefix/suffix are supported. A homepage, unrelated role or ambiguous title becomes `processing_failed` with `failure_kind: posting_description` and `requires_user_input: false`; it needs source resolution, not a candidate answer or automatic retry. A title match does not by itself prove description completeness or vacancy availability. Known Lever `/apply` and Ashby `/application` routes are read from their public description pages while preserving the stored job URL and artifact bindings.

Recovered public descriptions are saved in the queue before inference, with source URL, extraction method and an audit event. They survive model-limit interruptions and later summary-only scans; a fresh public availability check still precedes ranking. Persistence detects a changed source record and preserves historical prepared/submission bindings. New CV checkpoints use the saved source record, so this recovery does not itself force regeneration on restart. Previously assessed records with missing descriptions are not retroactively rewritten.

Discovery can reconsider previously unavailable, closed or expired records when substantive posting content changes. The ordinary public availability check still runs before ranking. Observation/posting timestamps alone do not trigger retries, and records with historical prepared materials, handoffs or submission attempts stay frozen. This does not establish that a vacancy has reopened; unchanged re-advertisements still require explicit review/retry.

After three job-specific technical failures, the worker stops that job as `processing_failed`, preserving its last error or public-page observation and identifying that a candidate answer is not required. Other jobs continue. Provider and shared browser failures retain their separate backoff. Use `retry JOB_ID` after diagnosing and resolving the cause. Changed posting content can restart an unprepared failed job with a fresh retry allowance; unchanged scans cannot. Historical prepared materials and handoffs remain protected. These recovery checks use fictional jobs and do not establish continuous employer-site reliability.

If the daily model-request allowance is exhausted partway through a batch or ranking correction, the worker stops that batch as `daily_limit` and keeps the affected job resumable. A local budget limit does not increment provider failures or job retries. Same-day restart respects the persisted allowance; after the next UTC day starts, processing can continue subject to other limits and genuine provider/browser backoff. Saved responses remain cached, including a failed initial response awaiting its bounded correction. This rollover has been verified with a simulated clock and fictional model transport, not a real 24-hour trial.

The optional experience screen skips obvious age and recency wording such as “16–17 year olds”, “eight years ago” and “the past ten years”. Full ranking still receives the complete description and applies the experience policy. A separate excessive experience duration continues to trigger the screen; this optimization does not establish eligibility or change the full assessment contract.

Remote-location assessments distinguish UK-remote work that can be performed from London from restricted regional residency, required office bases and relocation. “Remote” without an eligible country remains uncertain. The extra interpretation applies to remote-location candidates and carries its own assessment revision, so unrelated rankings retain their existing requests and cache keys. Discovery labels remain coverage hints, not proof of eligibility.

For a London/UK search, UK-remote candidates receive the same location scheduling priority as explicitly country-qualified London listings. Title preferences, freshness and employer rotation still order equivalent candidates; no eligibility is granted by scheduling. Read-only inspection of recognized Ashby application URLs uses the public description route while preserving the saved job/application identity.

Current explicit `pursue` choices move to the front of the ready queue before ordinary scheduling hints. They retain their existing relative order, and all other candidates retain theirs. Only choices bound to the current posting content count; changed postings, withdrawn choices and fields supplied by a posting cannot grant priority. Prioritizing a role does not bypass availability checks, fit/experience exclusions, retry backoff, daily limits or application ownership protections.

Ranking validation recovers model-added spacing next to emoji/currency symbols by returning the actual source span. An exact posting-location quote placed in summary evidence is retained with explicit location provenance; at least one description excerpt is still required. Changed words, numbers, currencies, paraphrases and title-only summary evidence remain invalid. These recoveries preserve the original assessment and do not require another model call or change the initial ranking request.

New rankings separate practical eligibility (`no_known_conflict`, `uncertain`, or `blocked`) from attractiveness (`strong_match`, `worthwhile_stretch`, or `poor_fit`). Each assessment includes quoted job requirements, candidate evidence references, and unresolved qualifications. A poor fit cannot advance to CV generation through a high score. Missing evidence does not establish a failed qualification; unresolved hard constraints remain visible for review. Scores are provisional judgments, not hiring probabilities or measured recommendation accuracy. Existing saved assessments retain their original format until explicitly reassessed; this change does not regenerate prepared CVs.

Assessment version 3 validates each requirement quote against the full description or the posting's separate location field and records the matched field. It cannot borrow a country from the candidate profile to complete a posting quote. General evidence excerpts still have to match the description. Reviews identify whether a requirement's quote came from the description or location. Literal quote validation is not a semantic correctness guarantee.

An explicit experience ceiling can be saved under `targeting.config.target_roles.seniority` using `mode: required_experience_range` and `maximum_required_years`. Ranking applies it to quoted mandatory experience requirements: a minimum above the ceiling blocks selection even with a high score. A 6–11-year requirement exceeds a five-year ceiling; 3–6 and 5+ do not. Preferred experience, unstated years and ambiguous alternatives are not converted into a higher mandatory minimum. This depends on correctly extracting and classifying the posting's requirements; it does not infer experience from a title.

Summary-only feed refreshes preserve an existing full description and its source metadata. The retained text keeps its earlier observation provenance; a new feed timestamp does not establish description freshness. Unchanged substantive content keeps prior ranking decisions. If the title, employer or location changes while the description is omitted, the old text is retained but marked for a fresh posting read; ranking cannot use it until that read succeeds. Fresh supplied descriptions replace retained text normally. Prepared and submitted evidence keeps its existing protection.

SmartRecruiters normalization uses the employer name supplied by the matched posting when available, so a descriptive board/query label does not become the applicant-facing company name. Missing employer metadata retains the configured fallback.

Discovery checkpoints are written to a separate file and published only after the write completes. On scanner timeout or nonzero process exit, discovery retains the last complete checkpoint and marks an active source as interrupted, while preserving completed-source history. An unreadable checkpoint raises an explicit error instead of becoming an empty successful scan. Recovery retains published progress; it does not claim to recover an unfinished source download.

Public reads retain unique application links even when a feed already supplied the description. Before ranking, the queue rechecks whether the newly observed destination belongs to a prior application or unresolved handoff. Observed Ashby, Greenhouse, Amazon and TikTok requisition links are journaled separately from job/CV inputs and reused by later discovery intake and prior-application checks. These aliases survive restart, are bound to the saved posting content, and use only the latest link observation; changed content invalidates the binding. Generic login/careers links cannot become recorded requisition aliases, and handed-off application evidence is not rewritten. Saved application URLs also exclude recognized shared portal patterns from identity matching while retaining the URL for navigation; explicit job paths and supported requisition query parameters still match. This is a bounded filter, not a universal portal detector. Same employer/title/location alone never authorizes a merge. Other route types still need their existing explicit URL evidence; this is not universal cross-site identity resolution.

A trailing preferred domain such as “requires six years, ideally in SaaS” does not erase the required duration. Preferred years and multiple-duration alternatives remain separate cases; this bounded rule does not parse every possible qualification sentence.

A parenthetical subtype preference attached to an example, such as “six years in fields such as advisory (large firms preferred)”, also leaves the required duration intact. Preferences about experience/tenure, preference wording elsewhere and multiple-duration alternatives continue to defer. The original source quote stays unchanged. This prevents an observed unnecessary full assessment after a valid experience-screen exclusion; it is not a general natural-language parser.

CV tailoring can choose among user-confirmed alternative employment titles saved in `employment_title_options`. Each option is bound to the original experience index, employer, dates and role, with an `operator_confirmed` source quote. The selected title must belong to that employer's exact allowed list; it cannot alter duties, dates or seniority claims. The material record retains the choice, relevance reason and profile source pointer. Without confirmed options, original titles are preserved. Title options invalidate CV checkpoints while unchanged substantive ranking inputs can still reuse their cache.

Assessment version 4 adds the original Career Ops named dimensions to the same evaluator: CV fit, career direction, compensation, culture/working conditions and red flags. Each has a 1–5 rating or an explicit unknown, an explanation and validated posting/candidate references. The existing overall 0–100 score remains a holistic judgment, not an average or conversion of the dimension scores. Reviews display the scorecard; historical assessments remain readable without fabricated dimension ratings. The automatic cutoff still requires calibration against user judgments.

Assessment version 5 records the exact source field for rubric quotes, including the supplied job title. Requirement evidence still comes from the description or location; title wording alone does not establish mandatory experience. The evaluator separates required experience from preferred modifiers within a mixed sentence. These instructions improve interpretation but do not establish semantic accuracy by themselves.

Assessment version 6 makes each canonical employment entry's non-bullet context citable as `employment.i`, linked to the same role's `experience.i.j` duty evidence. Dates and any stated work pattern are preserved exactly, including missing dates and year-only ranges. The evaluator must explain relevant duration without double-counting overlaps or treating intermittent projects, internships or part-time work as established continuous full-time experience. These instructions do not compute or prove a total. New rankings use the expanded context; saved assessments remain historical, and existing CV claim sources/checkpoints are unchanged.

Assessment version 7 distinguishes lower-priority allowed tracks from exclusions. Where the saved policy allows commercial/strategic finance, an FP&A label, forecasting or cost analysis alone cannot establish an accounting-led exclusion; the evaluator must identify the actual dominant duties. Accounting-heavy roles and explicit broader finance exclusions still apply, and missing candidate qualifications remain separate. This is a tested model interpretation rule, not a universal semantic guarantee. Updated instructions invalidate their ranking request keys; historical assessments and prepared documents are not automatically rewritten.

Assessment version 8 permits a bounded title-evidence exception for literal relocation clauses such as `(Relocation to Singapore)`. Only the extracted clause can support a hard-constraint location assessment; general title wording still cannot establish experience, years or qualifications. Reviews label that evidence as coming from the job title. The evaluator compares final placement with the saved search policy: recruiting-location labels alone do not override required relocation, while explicit alternative placement or optional relocation must be considered. Extraction and interpretation are bounded, not universal geography resolution. Historical assessments and existing documents remain unchanged until explicitly reassessed.

Assessment version 9 supplies code-calculated employment calendar evidence. Supported complete month/year ranges retain their original dates, endpoint distance, months touched and overlapping entries. A union counts shared months once. Year-only, open-ended, reversed and unsupported ranges stay unquantified. Calendar coverage cannot establish exact worked duration, continuous employment, full-time equivalence or time on a particular skill. A bounded validator rejects positive duration claims attributed to a uniquely identifiable, cited employer when they exceed its calendar extent, using the existing single correction allowance. It allows conservative rounding and defers ambiguous employers and explicitly uncertain claims; it does not validate every possible prose formulation. Reviews show the calculated calendar evidence. Older unprepared full assessments require refresh; experience screens and prepared/handoff records keep their existing contracts.

Use the [ranking evaluation workflow](EVALUATION.md) to compare frozen assessments with sourced user judgments, audit missed worthwhile roles and keep development cases separate from reserved evaluation cases. `evaluate` reports missing labels and predictions rather than claiming accuracy from model scores alone. A fictional example is included; evaluation requires no model or browser.

The full assessor rejects a hard experience-ceiling conflict when its cited, unambiguous mandatory lower bound is within the user's maximum. For example, a five-year ceiling cannot exclude a `5–7 years` requirement merely because its upper bound is seven. The existing single correction must reassess the score and fit; the validator does not assign a replacement score or claim that the candidate meets the required background. Repeated invalid output becomes an assessment failure. Older unprepared full assessments citing this policy as an unmet hard constraint require revalidation; other current decisions and validated experience-screen exclusions retain their existing freshness rules. This bounded check requires an explicit policy source and a parseable single duration; it is not universal interpretation of all experience wording.

Ranking source failures, malformed/missing JSON responses and schema-invalid responses share one correction allowance: at most two response attempts per assessment. The original posting and canonical facts remain the evidence, and every returned correction passes all normal source/experience checks. A request limit or provider interruption preserves existing retry/backoff behavior. If both attempts fail, the job becomes `assessment_failed`, with `requires_user_input: false`, and other jobs continue. It will not loop automatically on unchanged evidence. Inspect the cause before an explicit `retry JOB_ID`; a changed posting also permits reassessment. Reviews hide stale scores for a failed assessment.

Before full queue ranking, an explicit experience ceiling can trigger a compact eligibility screen when the description contains a potentially higher duration. The same configured model reads the full posting and ceiling, without candidate CV details. Only a validated mandatory minimum above the ceiling can stop the job as `not_selected`; the record has an exact posting quote and no fit score. Reviews label it as an eligibility screen and suppress older scores. Preferred experience, alternatives, uncertainty and invalid screen output fall through to full ranking; provider failures retain backoff. Roles without a potential higher duration bypass this extra call. The screen has no correction loop, so a deferred screen can add one request to the existing full-ranking allowance. This saves work for clear exclusions but can increase cost for deferred cases. The trigger and model interpretation are bounded and do not prove universal requirement recognition.

Structured-output failures retain private response text, available usage and diagnostic metadata under the model cache's `failures/` directory; `ranking-validation.json` links to that evidence. Failed initial requests also have separate `.invalid.json` markers, allowing a validated correction to be reused without repeating the failed request. These markers are errors, never accepted responses or candidate facts. An explicit queue retry does not discard them: after investigating a technical failure, fresh inference requires changed inputs or clearing only the identified request's cache/marker while retaining its audit. Malformed output in a non-ranking pipeline stage stops that job as `model_failed`, also without requesting candidate facts; `retry` supports that state. Login failures, process errors and timeouts remain provider interruptions.

## Setup on Windows

For discovery and assessment without application preparation, use `watch --profile local/profile.json --boards local/boards.json --rank-only`. The worker retains its job/request limits and restart state, leaves current assessments alone, and honors explicit choices on eligible below-cutoff roles. It reads public postings but does not generate CVs or fill employer forms. `--rank-only` and `--prepare` are mutually exclusive.

Unprepared `ranked` and `not_selected` assessments become candidates again when their assessment profile or assessment version differs from the current one. New assessments retain the full original profile hash for provenance and a separate assessment hash excluding only `discovery_preferences`: changing intake/scheduling settings alone does not invalidate a decision. Changes to other profile fields still require refresh. Legacy records without this separate hash conservatively use the full profile hash; read operations never infer missing historical context or rewrite records. Current assessments stay untouched; an explicit pass does not cause a refresh loop. Prepared documents, manual handoffs and submission states keep their existing ownership rules. Reviews supplied with `--profile` hide stale scores and label the need for reassessment. `status --profile local/profile.json` does the same in its bounded summary; without a supplied profile it reports `assessment_profile_checked: false` and retains historical values. Refresh uses the ordinary budgets, public posting checks and response cache. It does not imply a fresh inference request when the substantive inputs still match a valid cache entry.

Queue scheduling can use explicit lower-interest title phrases in `discovery_preferences.title_filter.deprioritized`. These wait behind other roles in the same location group without being rejected. Obvious senior-title signals such as `Senior`, `Director` and `Principal`, and distinct early-career labels such as `Intern` and `Graduate`, also wait behind otherwise equivalent roles. This preserves a 1–5-year search focus without treating a title as proof of mandatory experience. Overlapping aliases count once, and phrases match at word boundaries. When the search location is London, UK, country-qualified London leads bare London; Canadian/US/South African namesakes receive no London boost. These scheduling hints do not establish eligibility or replace full-description assessment.

Within the same location/title priority, a configured `discovery_preferences.max_posting_age_days` orders dated recent postings first, unknown dates next, and older postings afterward. The scheduler uses `postedAt`, never the discovery timestamp; implausibly future dates remain unknown. Within each equivalent group it rotates employer labels, starting with the most recent postings. Labels are matched after case/whitespace normalization. Optional `discovery_preferences.employer_rotation_groups` can explicitly share a slot across verified labels, for example `{"Example recruiting": ["Example UK Ltd", "Example Europe Ltd"]}`. Unlisted labels remain separate; similar names, domains and corporate ownership are not inferred. Empty or ambiguous groups are rejected. Grouping changes only work order: original employers, records, priorities, user choices and fit scores remain intact. Without an age preference, no default freshness cutoff is imposed. Every candidate remains available, and full-description ranking still decides fit and constraints. This orders the next work batch; it is not a recommendation score or proof that a dated posting is open.

A private `preparation-policy.json` containing `{"paused": true}` blocks CV generation and application entry points. Put it beside the profile or in the data directory; the default runtime also checks `local/preparation-policy.json`. Ranking and fictional fixtures remain available. Pause checks run at application entry and between pipeline stages; they do not cancel an operation already in flight or update an older running process. Resume preparation only after the user requests it.

Requires Python 3.12+, Node.js 22+, Google Chrome (or Edge), and Codex CLI.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
codex login
.\.venv\Scripts\python.exe -m joblazy doctor
```

Use `JOBLAZY_CODEX` if Codex is not on PATH. Run from your normal Windows account: Codex's sandbox account may report no login even when your account is signed in. Login uses the supported Codex account flow. Account access and usage limits apply; JobLazy pauses rather than changing providers. Default runtime model: `gpt-5.6-terra`; change with `--model` after checking availability and output quality.

Model requests share repeated source-ID enums through JSON Schema definitions instead of sending each list repeatedly. Candidate facts, task instructions and output validation remain complete. Cache identity still uses the original schema, so existing valid responses are reused without another request. New response metadata records original and transmitted schema sizes alongside actual token usage; schema size alone does not establish runtime cost, speed or recommendation quality.

The exact effective logical request is saved privately under `model-cache/requests/<input-key>.json` before cache lookup or inference. It includes the task, input data, original schema, model and cache-contract settings; hashing the saved object reproduces its input key. Use it when freezing comparisons: observed posting fields and caller transformations may differ from the saved queue record. A cache replay can record the matching request now, but does not establish that it was captured at the original invocation time. Keep these files private alongside response caches; the compact usage journal still contains no prompt text.

Use `python -m joblazy usage` to read today's recorded model calls, or `usage --day YYYY-MM-DD --job JOB_ID` for one UTC day/job. Private invocation records under `model-cache/calls/` distinguish inference attempts, successful cache reads, cached failures, available provider tokens and elapsed model-call time. Queue calls are attributed to the job and ranking, tailoring or application-answer stage; calls outside that scope remain unattributed. No prompts or responses are copied into this journal. A record is persisted before inference so a killed process leaves an incomplete attempt with unknown usage. Cache reads never count the original response's tokens again, and missing token fields remain unknown rather than zero. Token fields are separate provider counters, not quantities to add together. These records begin with this instrumentation; old cache metadata is not reconstructed as invocation history. The daily request-limit ledger remains separate and attempts are not confirmed billing. Reporting makes no model, browser or queue changes.

The `workflow` section records whole processing-attempt time separately from model time. New pipeline attempts write a durable start record under `applications/JOB_ID/processing-attempts/` and record elapsed time and outcome only when the attempt finishes normally. Reports group attempts by start UTC day, job, requested mode and fixture-origin flag, keeping ranking separate from CV generation and preparation. A terminated process or interrupted preparation keeps an incomplete record with unknown total duration; restart creates a new record. Older work has no reconstructed timing. This measures processing, not queue waiting or human review time, and recorded outcomes alone do not establish preparation success or submission receipts. The same report counts journaled job choices, scoped-answer transitions and operator outcome reports by job/day. These are recorded actions, not total human interventions: manual browser edits, chat clarifications and other unjournaled work remain unmeasured.

## First run

An explicit job choice can override the numeric cutoff for an otherwise eligible strong match or worthwhile stretch:

```powershell
python -m joblazy choose JOB_ID --decision pursue --note "I want to pursue this role"
```

`pass` skips processing that posting; `automatic` removes the numeric preference for future processing. Choices are recorded separately from candidate facts and model scores, bound to the posting content, and shown in reviews. They do not override poor-fit/hard-constraint decisions or reopen submitted, uncertain or manual-review applications. A materially changed posting requires a fresh choice for a cutoff override. Recording a choice alone does not fill or submit a form.

For a new profile, copy the fictional examples into the private local folder and replace their contents with your own facts and search preferences. See [profile setup](PROFILE.md). Career Ops is not required.

```powershell
New-Item -ItemType Directory -Path local -Force
Copy-Item examples/profile.json local/profile.json
Copy-Item examples/boards.json local/boards.json
```

If you already have canonical Career Ops files, the optional importer can start that profile instead:

```powershell
# Import only canonical facts and targeting from your existing Career Ops folder.
.\.venv\Scripts\python.exe -m joblazy import-profile C:\path\to\career-ops
```

After editing the private profile and board list:

```powershell
.\.venv\Scripts\python.exe -m joblazy doctor --profile local/profile.json
# Edit a private board list. The example is a scanner smoke test, not a search strategy.
.\.venv\Scripts\python.exe -m joblazy scan local/boards.json
.\.venv\Scripts\python.exe -m joblazy run --profile local/profile.json --limit 5
.\.venv\Scripts\python.exe -m joblazy status
.\.venv\Scripts\python.exe -m joblazy review
```

`run` ranks full job descriptions, rewrites CV content from cited facts, independently reviews claims, renders the existing one-page template and saves the resulting PDFs. It does not fill application forms unless `--prepare` is supplied. `--prepare` is an experimental engineering operation that fills/uploads and closes the temporary browser session. Use `assist` below to keep a browser open for review. No live-submit CLI is exposed yet. Use `--browser-channel msedge` for Edge.

To review fit before generating CVs, use `run --profile local/profile.json --rank-only --limit 10`, then `review`. This saves above-threshold candidates as `ranked` and rejected or below-threshold roles as `not_selected`; it makes no CVs or form actions. Ranked roles support read-only inspection and scoped answers, and can continue through `run --job JOB_ID` or `assist JOB_ID` with the profile argument. A normal worker also continues ranked candidates. Unchanged model inputs reuse the shared cache; changed profile, posting or ranking instructions trigger reassessment. `--rank-only` cannot be combined with `--prepare`. One-off `run` calls share the persisted daily limits used by `watch`: `--daily-jobs` and `--daily-model-requests` default to 10 and 50. An exhausted limit returns `daily_limit` before a browser opens; uncached model requests reserve a slot before dispatch, while cache hits do not.

For ranking calibration, `record-judgment` saves one explicit user decision to a new development-set dataset copy, bound to the frozen job content. It rejects holdout roles and never triggers inference, browser work or queue changes. See [`docs/EVALUATION.md`](EVALUATION.md).

The normal queue now reads each selected public posting before model work, including roles with full feed descriptions and runs reusing CV checkpoints. `availability.json` records the time, response, destination and observed headings. Explicit closure notices stop as `posting_closed`; elapsed structured deadlines stop as `posting_expired`; HTTP 404/410 and missing-job notices stop as `posting_unavailable`. An expired deadline or missing page is not proof of closure. Rate limits, server failures and browser read failures use the existing bounded retry handling; access failures pause for inspection. An HTTP 200 response with no detected closure is not proof that applications are accepted. Older posting dates alone never close a job. Use `retry JOB_ID` for an explicit fresh check of a stopped posting; unchanged scans do not silently reopen it. Fictional local workflows and direct offline ranking evaluations do not perform this network check.

For branded pages using `gh_jid`, the public reader can select a visible embedded Greenhouse job with an exactly matching token. It records the embedded description URL and rejects ambiguous frames. If neither a matching embedded posting nor a matching visible job heading is exposed, it stops instead of ranking the careers-page introduction. This is a bounded provider-specific recovery, not a general guarantee of full-description extraction. Visible-text fallback excludes form elements.

`status` reports total jobs, counts by state, today's UTC job/request usage and up to 20 recent processing results. Use `status --limit 5` for a shorter view or `status --all` for the full JSON job listing, including unprocessed discoveries. Status is read-only and does not recover or retry interrupted applications; a displayed `processing` state is not proof that a worker is alive.

Audit the saved discovery pool before treating queue size as useful coverage:

```powershell
.\.venv\Scripts\python.exe -m joblazy coverage --boards local/boards.json --max-age-days 45
```

This writes private `runtime/coverage.json` without scanning, using a model or changing application states. It separates explicitly UK-qualified London labels, bare London, other cities named London, and remote roles whose eligibility needs verification. It reports employer labels, posting age, observation age, description-length coverage and possible duplicate groups across different URLs. None of those establishes employer availability, full-description completeness or personal fit. Suspected duplicates are reported rather than merged.

The board configuration can optionally include a top-level `"location_classes": ["london_uk_explicit", "london_country_unverified", "uk_remote_candidate"]`. This limits new intake to those location categories while retaining the complete fetched observations in the scan checkpoint. It does not remove older queue records. Bare London and UK-remote candidates still require eligibility checks; other remote locations stay outside this intake filter. Omitting the setting retains all locations. Invalid categories stop before scanning.

Country-qualified London labels include `London, GBR`, `GB-London` and `London, U.K.`. `East London, UK` is retained; bare `East London` stays uncertain, and South African or Canadian namesakes stay separate. Country codes must belong to the same location group: a flattened `London · GBR` list does not establish the association. Corrected classifications change coverage counts without creating new jobs or proving suitability.

Composite phone controls derive their calling code, national number and uniquely established routing region from the supplied international number using pinned `phonenumberslite` metadata. A Country field within a Phone section cannot fall back to residential country. Native and supported ARIA country selectors require an exact, unambiguous committed choice before the linked national number is filled. Phone verification checks the selected country and parses the displayed number back to the original international number, including national formatting. Missing international prefixes, unsupported extensions, ambiguous country choices and unsupported widget structures remain unresolved. Residence and preferred work location use their own sources. Live employer compatibility must still be checked per supported form.

Amazon/AWS discovery reuses the upstream public-search provider. For London, use `"provider": "amazon"` with `"amazon": {"normalized_country_code": ["GBR"], "normalized_city_name": ["London"]}` in a board entry. The observed endpoint ignored free-text `loc_query` and the incorrect `normalized_city` key as location filters. The wrapper preserves basic/preferred qualifications and all structured locations, including a secondary London office. Calendar posting dates have day precision. The provider is bounded at 20 pages of 100 results; fewer distinct results than the reported match count produce a warning. This does not establish current employer availability.

The Muse supports targeted discovery through `"provider": "themuse"` and `"themuse": {"company": "Uber", "location": "London, United Kingdom"}`. These optional string filters apply to every page through the existing provider; unsupported or empty filters fail explicitly. The retained provider has a 100-page cap. Fewer distinct returned URLs than the feed's reported total produce an incomplete-result warning. Targeted queries can recover employers' roles missed by the broad feed's first 100 pages. Feed dates and descriptions still need employer availability checks before preparation.

SmartRecruiters discovery reuses the unchanged MIT provider from the Hermes donor. Set `"provider": "smartrecruiters"`, `"careers_url": "https://jobs.smartrecruiters.com/COMPANY"`, and optionally `"smartrecruiters": {"city": "London", "country": "gb"}`. These filters persist across list pages. JobLazy retrieves posting details from exact matching public API references, retains every supplied description section, country-qualified location, work arrangement and publication date, and reports missing or failed details as source warnings. The list provider has a 50-page cap; a reported total above the distinct returned count also produces a warning. Successful discovery does not establish form support or permission to apply. See the [official public API documentation](https://developers.smartrecruiters.com/docs/endpoints).

Intake joins exact recorded application routes, including equivalent Ashby posting/application URLs and the two supported Greenhouse board-host forms. It retains the existing job ID and source URLs and preserves prepared/manual-review records. If several existing records match, intake reports the ambiguity and skips that observation. Same-title roles are not automatically merged. Ashby postal-country evidence is retained per location; legacy flattened city/country lists cannot establish a country for bare London.

New scans preserve per-source/query observations in `runtime/source-registry.json`, including failures, warnings, last successful fetch and seen job IDs. A warning or page cap does not establish exhaustive coverage. Historical query attribution stays unknown where it was never recorded. Per-source new-job counts may overlap when multiple sources see the same newly added job; the scan's `new_unique_jobs` counts unique additions to the whole queue. Descriptions and explicit location lists omitted by minimal upstream records are retained when present in raw feed responses; missing feed descriptions still require enrichment.

Deliveroo's current feed works through the existing `ashby` provider with `careers_url` set to `https://jobs.ashbyhq.com/deliveroo`. Its branded careers site exposes Ashby-backed roles through WordPress; the old Greenhouse source should not be treated as current coverage. As with other sources, a successful scan establishes an observation, not suitability or permission to reapply to a previously handled posting.

Reviewed materials are checkpointed. A later `run --prepare` can continue jobs in `materials_ready`; use `--job JOB_ID` to choose one. Matching checkpoints avoid model calls and PDF regeneration. Changed job content, candidate facts, targeting or saved files invalidate the checkpoint.

New version-3 document checkpoints ignore `discovery_preferences`, which controls intake and scheduling rather than CV evidence. Changing posting-age or discovery title filters can therefore reuse the exact reviewed CV, including after restart. Live assisted resumption also permits that change while preserving browser edits and retained attachments. Career facts, targeting rules, residence, printed contacts and unknown material inputs remain bound. Version-1 and version-2 checkpoints retain their original validation rules; they are not silently upgraded or declared current after profile changes. This reuse has been verified on fictional local forms, not a new employer application.

Use `review --profile local/profile.json` to check saved CVs against current inputs. A matching document checkpoint keeps the “Tailored CV” link. An intact PDF whose checkpoint no longer validates remains available as “Saved CV (review required)”; without a supplied profile, the link says “Saved CV (profile not checked)”. These labels preserve application history without declaring old documents current. Changed or missing PDF bytes remain unlinked. Viewing a review never regenerates CVs or changes application ownership.

Preparation rechecks public application destinations independently of those CV checkpoints. Explicit employer links (including “Apply at …”), The Hub's current public posting link, and The Muse's published `job.applyLink` can lead through up to four pages. Muse metadata must match the current company and posting slugs; unrelated or ambiguous routes are rejected. Known aggregator pages without an employer destination pause rather than becoming application forms. Ambiguous links, employer sign-in and failed HTTP responses also pause before filling. The original listing remains the queue identity, and `application-route.json` records the observed route, including failed destination statuses. Reviews show saved inspection failures alongside fit judgments. Resolving a destination does not prove its form is supported.

For queued live `run --prepare` work, the employer-route check runs after fit assessment and before new CV drafting or rendering. An inaccessible route preserves the ranking and pauses the application without spending further calls on its CV. Rank-only and CV-only requests remain independent of application-route access. Assisted mode retains its separate visible handoff/sign-in flow.

Teamtailor's observed application overlay can open through its specific form-entry control, declining optional cookies when that exact control is present. Its label-based required markers and grouped choices are recognized. Demographic and application-consent choices require explicit saved answers. Local tests cover filling, PDF submission and missing-answer handling; live checks cover navigation and field inventory only.

Address-derived location autocompletes use the supplied city, region and country and require a unique exact choice in that widget. A city-only namesake, an option from another dropdown, or typed text without a committed choice cannot pass. Plain city text fields still use the supplied city. Unsupported labels remain unresolved; the location selector does not infer geography or silently accept a similar city.

Ashby's observed calendar fields are recognized as dates even when their HTML input is text. A confirmed full date is selected in the calendar and checked against its selected day; a typed sentence does not count as a date selection. The adapter supports the observed English month/year headings and at most 24 months of navigation. Native date fields receive ISO dates. Month-only availability remains suitable for ordinary text fields.

For Ashby file controls, JobLazy requires the selected PDF hash and matching filename in a completed attachment display, with enabled replacement and deletion controls and no observed rejection. Selection alone is insufficient. It waits up to 15 seconds, makes one upload attempt per empty field, and pauses on pending, removed or unverified attachments. This verifies the observed form state, not employer acceptance at submission. The detector has local regression coverage and live empty-form verification; a new supervised upload remains to be verified.

For Teamtailor's immediate uploads, JobLazy checks the retained native file's SHA-256, a successful upload response, and the matching enabled attachment reference in the form. Replaced or disabled file pickers do not trigger repeated uploads. Waiting is bounded to 15 seconds per upload; failures, pending uploads, changed bytes, mismatched references and unverifiable existing attachments stop preparation. This contract has been reproduced with a local upload server; a real employer upload still needs a supervised trial.

## Use the local dashboard

Start the local browser dashboard with:

```powershell
.\.venv\Scripts\python.exe -m joblazy dashboard --profile local/profile.json
```

It binds to `127.0.0.1` only and shows the saved shortlist, current usage and Codex connection. Use **Open posting** to read the employer listing, then **Prepare in browser** only when you want JobLazy to open that role's visible preparation session. The preparation window uses the same `assist` workflow below and stops before Submit. The dashboard does not run ranking or start applications in the background.

## Review one application in the browser

```powershell
.\.venv\Scripts\python.exe -m joblazy assist JOB_ID --profile local/profile.json
```

This opens a visible Chrome session, reuses or generates verified materials, fills supported fields and uploads the CV. It stops before the final Submit control and keeps the page open for you. If employer sign-in is needed, sign in normally and type `prepare` in the terminal to continue. Wait for preparation to finish before editing the form yourself. Review missing answers and uploaded material in the browser, then finish manually. Press Enter in the terminal when done to close the session.

While a prepared application is paused, save scoped answers with the `answer` command in another terminal, then type `resume` in the waiting assisted session. Resume reloads the profile and continues the same form without navigation. Browser edits remain untouched across repeated resumes; a conflicting saved value is shown as a verification issue. Existing CV attachments are checked again, and removing an attachment does not trigger an automatic replacement. Form-only contact/postcode changes can be used when they leave the CV and matching inputs unchanged. Changed career facts, residence, targeting, material files, document or step pause resume. Closed sessions still require outcome reconciliation before another attempt; resume does not reopen them or enable Submit.

Employer sign-in state is saved in the private `runtime/browser-profile/` directory. JobLazy never reads your password or copies your normal Chrome profile. Keep this directory private. Only one assisted browser session uses it at a time. The queue can continue working on other jobs after the page is handed to you.

The job enters `manual_review` before its employer page opens. That state survives closure or interruption, and excludes the job from automatic retries. Record the verified outcome with `reconcile` below even if you closed the browser without submitting. Neither closing the page nor a successful fill is treated as a submission receipt. Saved sign-in persistence, manual completion and restart protection have been tested with local fictional applications; a supervised live-employer trial is still needed.

Read application questions before entering personal details or uploading a CV:

```powershell
.\.venv\Scripts\python.exe -m joblazy inspect JOB_ID --profile local/profile.json
.\.venv\Scripts\python.exe -m joblazy show JOB_ID --profile local/profile.json
```

`inspect` opens a fresh browser, follows the public employer route and reads the visible application controls. It uses your profile only for local answer mapping; it never fills fields, uploads files, calls a model or changes the job's queue state. Employer sign-in, unavailable forms and ambiguous routes are recorded for review. It cannot discover later form steps that require supplying data first. The resulting `form-inventory.json` belongs to the exact posting and material profile; changed inputs require another inspection. Active processing, submitted, uncertain and manually owned applications cannot be inspected through this command.

Resolve an observed form question with an answer scoped to that exact application:

```powershell
.\.venv\Scripts\python.exe -m joblazy show JOB_ID
.\.venv\Scripts\python.exe -m joblazy answer JOB_ID --profile local/profile.json --question "EXACT QUESTION FROM SHOW" --value "YOUR ANSWER"
.\.venv\Scripts\python.exe -m joblazy run --profile local/profile.json --job JOB_ID --prepare
```

The answer command accepts an observed unresolved question and checks known choices. It saves the answer privately with its application scope, operator-source marker and timestamp. Existing input exceptions become retryable; manually owned applications retain `manual_review` and await an explicit `resume` in their open session. Scoped answers alone do not invalidate the CV. Account credentials are not application answers.

For read-only inspections, a discovered, CV-ready or prepared job keeps its existing state when an answer is saved; saving an answer does not authorize a browser operation. `show --profile` and `review --profile` remove questions resolved by current saved answers, and an explicit correction to an already-saved scoped answer is supported. Inspection and answer commands refresh the local review page; portable bundles include the saved inspection questions and boundaries too.

The same answer refresh and correction work for paused browser preparation. Refresh uses the last saved field metadata and preserves other unanswered questions and reviewed narrative drafts. Older reports without field metadata retain their outstanding questions until another application check. Saving an answer does not update an open employer form or verify its current values; continue preparation to check the actual form.

Required open-ended experience and role-fit questions can be drafted from canonical facts and the job description. Each draft carries source IDs, passes metric and length checks, and receives a separate factual review before filling. Drafts stay under the application directory in `answer-drafts.json`; they never become profile facts. Missing experience, commitments, consent and choice questions still require saved answers. Model access may therefore be needed during preparation even when the CV is already cached.

`retry JOB_ID` resumes other exceptions after you resolve them. Submitted and uncertain submissions cannot be retried through this command. Queue items that need input do not consume the next batch's processing slots.

Open `runtime/review.html` for the local shortlist: fit reasons, outstanding gaps, verified PDF links and any application-answer drafts. `run` and active `watch` cycles refresh it automatically; `review --limit 100` rebuilds it on demand. It has no server or scripts and performs no application actions. The report and linked CVs are private material.

To package up to 20 verified CVs for review, use the current profile:

```powershell
.\.venv\Scripts\python.exe -m joblazy review --bundle --profile local/profile.json --limit 20
```

This writes `runtime/review-bundle.zip` (or `review-bundle.zip` under `--data`). Extract the whole archive and open `index.html`; its CV links work after moving the folder. The manifest records the selected jobs, source links, fit assessments and PDF hashes. Export checks the full saved posting/profile/material checkpoint and the actual PDF page count, selects by fit score, and reports the actual included count if fewer than the requested number are valid. It excludes submitted and uncertain submissions, preserves manual-review ownership, and never starts model or browser work. An empty or failed export preserves the previous ZIP.

The pack contains verified CVs, not necessarily complete applications. Questions and draft answers reflect the last saved application check and still need review against the current employer form. This command does not refresh forms, fill fields, upload files, submit applications or retry jobs. `--output` remains an HTML-review option; bundle output stays in the private data directory.

If you check an uncertain outcome in the employer portal, record what you found:

```powershell
.\.venv\Scripts\python.exe -m joblazy reconcile JOB_ID --outcome submitted --note "Verified the application receipt in the employer portal."
# If you verified that it was not received, keep it paused until an explicit retry:
.\.venv\Scripts\python.exe -m joblazy reconcile JOB_ID --outcome not-submitted --note "Checked the portal and confirmed no application was received."
```

Reconciliation records your statement as `operator_report`, saves an audit entry and refreshes the shortlist. It performs no browser action. `not-submitted` moves an uncertain item or a manual handoff to `needs_input`; an explicit `retry JOB_ID` or `assist JOB_ID` is required to attempt it again. An existing recorded submission cannot be undone this way.

## Continuous operation

Run from a normal Windows terminal with your existing Codex sign-in:

```powershell
.\.venv\Scripts\python.exe -m joblazy watch --profile local/profile.json --boards local/boards.json --daily-jobs 10 --daily-model-requests 50
# From another terminal, request a stop after the active cycle:
.\.venv\Scripts\python.exe -m joblazy stop
```

The default runner scans hourly, checks the queue every minute, and processes up to three jobs per cycle. It creates ranked, reviewed CVs; employer form preparation still requires the explicit experimental `--prepare` option. Use `--max-cycles 2` for a bounded trial. A normal start clears a previous stop request.

Queue progress, scan deadlines and retry backoff survive restart. Daily limits reset at midnight UTC. Job attempts in the same queue count toward the job limit; the request limit counts uncached worker model calls, including failed attempts. It is not an account-wide token or money limit. Cache hits do not consume request slots. Provider outages back off from 15 minutes to six hours, and a repeatedly failing job becomes an input exception after three worker attempts.

An observed browser disconnect stops the current batch and leaves later jobs untouched. The worker records a separate browser retry delay, starting at two minutes and increasing to one hour, which survives restart. This shared failure does not consume the affected job's three job-specific retries, though an attempted job still counts toward the daily job limit. A later cycle launches a fresh browser. Posting-read diagnostics and uncertain-submission protections are preserved; a connected browser's ordinary per-job failures retain their existing handling. This does not restore a user's manually edited browser session.

When another queue command or assisted preparation holds the run lock, the worker reports `busy` and tries again on its next ordinary cycle. Lock contention does not consume a job attempt or add a provider backoff. A second continuous worker is rejected by a separate worker lock.

Malformed profiles or conflicting form/CV contact details produce `profile_input` before discovery or model requests. Correct the private profile and the worker rechecks it on its next ordinary cycle. Missing name parts or phone numbers are warnings: CV generation can continue, and forms requiring those answers pause for input. Use `doctor --profile local/profile.json` to inspect the errors and warnings before starting.

No model or browser runs while the queue is idle. A process lock prevents a second continuous runner; ordinary queue commands can run between cycles. `runtime/worker-state.json` records the last cycle and PID, but is not proof that the process is still alive. Keep the terminal running and the computer awake. Automatic Windows startup and an overnight reliability trial are not implemented or verified yet.

## Verify locally

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe scripts/demo.py
```

The demo uses fictional facts and canned model responses, with real PDF generation, browser filling, PDF upload to a local server and submission confirmation. It covers embedded forms, résumé-parser corrections, multi-step applications, missing answers and uncertain outcomes. The test suite also covers form patterns observed on live Greenhouse and Lever pages, including unnamed fields, grouped questions and committed location selections. Results, per-step screenshots and PDFs are under `runtime/demo/`. This verifies integration mechanics, not model quality or every ATS.

## How it works

Python owns a SQLite queue, model requests, evidence checks, and Playwright browser execution. Two small Node commands reuse Career Ops's ATS providers and HTML CV renderer. JobPilot's scan/fill JavaScript and deterministic Python mapper provide the form machinery. The upstream dashboard, server, scheduler, Ollama integration, outreach and email tools are inactive.

Prior submissions and unresolved handoffs remain protected queue records. Before model work and again before form filling, JobLazy compares exact known application routes against other protected records; matching titles or companies alone do not establish a duplicate. The browser check covers a broker URL that only resolves to a previously handled employer posting later. Imported history retains its evidence source and is not counted as a new JobLazy submission. Coverage reports distinguish history-only rows and imported outcomes from newly discovered records. Unknown or rejected outcomes never authorize another attempt automatically.

Queue ordering uses inexpensive location and title hints before the full job-description assessment. A matching title earns one bonus, even if it matches several saved aliases. Adding synonymous or overlapping search phrases therefore cannot give a role extra priority or outweigh the location hint. These hints do not reject roles or establish fit, eligibility or seniority.

Candidate identities, dates, and employers stay fixed. Generated bullets carry source IDs; changed metrics fail before rendering. A separate model review checks factual support. This is an engineering check, not a mathematical guarantee of truthful paraphrasing; review real model outputs during calibration.

CV claim-grounding checks and semantic factual review share the existing maximum of two repair attempts. Each revised draft passes the same source/metric checks and independent review before rendering. Exhausted claim repair stops as `model_failed` with `failure_kind: tailoring_validation` and `requires_user_input: false`; the rejected draft and issues are saved privately in `tailoring-validation.json`. Other jobs can continue, and unchanged failed jobs do not loop automatically. This does not turn a model-output problem into a request for candidate facts. Genuine missing facts, invalid source profiles and other preparation failures retain their separate handling. Application pauses still prevent real drafting and preparation.

The Codex worker uses [documented per-invocation configuration](https://learn.chatgpt.com/docs/config-file/config-reference) for compact instructions, disabled shell/web/app tools, and a minimal skill catalog. This avoids paying the full coding-context overhead for each ranking or writing task. Usage metadata is saved beside cached results; no global Codex configuration is changed.

Ranking context version 2 sends repeated long profile passages once in the candidate-fact dictionary, with explicit references in the resume and targeting structure. All values remain recoverable, including role identities, dates, uncertainty and extra fields. Identical text attached to multiple source IDs stays inline to preserve its context. Fetch timestamps and source bookkeeping are excluded from ranking inputs, allowing observation-only refreshes to reuse the cache; job content, preferences, career facts and contract changes still require reassessment. In one comparable live development case this reduced input tokens by 11%; output tokens and elapsed time increased slightly, so it does not establish a general cost, speed or recommendation-quality improvement.

File hashes are checked on disk and in the browser. Planned answers are checked against actual control values before advancing each step. Submission intent is committed before the final submission click. Only a new explicit receipt in the application frame on its original origin counts as success. Error/contradictory messages, changed text around an old receipt, unrelated-frame messages, redirects without a receipt, disappearing forms and transport ambiguity remain `submission_unknown` and are never retried automatically. Receipt observations are saved for review. Unsupported receipt wording or a move to another origin requires reconciliation.

If an application iframe is removed after a Next/Continue action, JobLazy locates a unique visible replacement within the existing eight-second step deadline. It stops if multiple application forms are visible, and checks for sign-in or challenges before filling each step. A local two-origin fixture covers replacement, server-retained contact details, exact PDF receipt, missing required answers, competing frames and later sign-in. This does not establish support for every employer's embedded workflow.

Private data is ignored by Git. Before publishing, run `scripts/check-public.py`, inspect staged files and retained third-party notices. Nothing has been published by this prototype.

`python scripts/verify-vendor.py` checks every retained third-party file against its existing manifest without rewriting hashes. For a source ZIP, extract it into a clean folder and run `python scripts/check-public.py --source-tree` before installing a virtual environment or creating local/runtime files. A normal Git audit rejects folders that merely inherit a parent repository; a zero-file scan cannot pass. To check your private profile values against an export, add `--private-profile C:\path\to\private\profile.json` without copying that file into the export. These checks detect known patterns and values; inspect the actual release contents as well.

See [current status](STATUS.md) and [reuse attribution](../THIRD_PARTY.md).

See [the autonomy roadmap](AGENTIC-ROADMAP.md) for proposed goals and their completion evidence.

