# Searching with JobLazy

After confirming your CV and future-work preferences, choose **Build my search**. Review the proposed title phrases, location and sources, then save the plan.

**Search and review** starts six complementary Luna missions with at most three concurrent model workers. The friend preset also uses Luna for the preliminary shortlist. The personal preset retains Astra review. **Fetch vacancies** and **Rank matching roles** are separate controls; opening saved results or refreshing the page does not start a new delegated search.

## Retrieval and coverage

Each new web search has a unique run identifier. The six missions divide requested role families, new employer discovery and coverage gaps. Each requests one search call with up to three queries and eight leads. Observed tool events are validated after execution; this is not a hard hosted-tool spending cap. Search workers receive future-work preferences rather than candidate contact details or full CV facts.

Exact identities remove duplicate links before verification. A bounded reader pool checks public Ashby, Greenhouse and Lever posting APIs, with individually owned browser fallbacks for unsupported or inaccessible routes. Source content and matching posting identity are checked before a role is accepted. Verified boards can enter a persistent registry for bounded future scans. Board expansion applies title/location filters; it does not turn every posting into a recommendation.

Supplementary sources include The Muse, Remotive and Arbeitnow. They cover only part of the market and vary in geography and freshness. Remotive listings are delayed by 24 hours. The Muse documents registration requirements beyond testing; resolve access before broader rollout. Source names and original links are retained. [Remotive API documentation](https://github.com/remotive-com/remote-jobs-api) · [The Muse API documentation](https://www.themuse.com/developers/api/v2).

No employer list is loaded from the developer's personal data. **All saved roles** means the local queue, and **All ATS roles** means its direct-ATS subset. Neither means all vacancies online.

## Caching and recovery

Unchanged supplementary feeds are reused for six hours; failed-source reports have a five-minute retry interval. Each supplementary feed has a 45-second process deadline and retains completed partial checkpoints. The preliminary shortlist is published before supplementary feeds finish.

A new delegated web search dispatches fresh missions. **Resume saved search** instead reuses completed missions and recent verification artifacts from that interrupted run. Saved operations are never restarted merely because a browser reconnects. Reports disclose observation times, failures and sampling limits.

Preliminary decisions can be reused after fresh matching source checks when candidate facts, substantive posting content, model and review contract still match. Retrieval timestamps alone do not force another review. Changed facts or job requirements do. Similar job titles alone never establish duplicate identity.

## Interpreting recommendations

A preliminary recommendation contains evidence and caveats, not a complete fit score or permission to submit. Select a role and request its full assessment before generating and reviewing a CV. Missing qualifications remain visible; preferences do not establish experience or eligibility.

The local safeguards count processing attempts separately from uncached model-request reservations. Six concurrent scouts share one account and one ledger. See [usage](ECONOMICAL-USAGE.md).

## Current live evidence

A 29 September Luna-only trial used a fictional London operations candidate. Intake took 8.875 seconds and planning 12.203 seconds. All six scouts completed with three-worker concurrency: 18 leads, three duplicate leads, three independently verified postings and 12 rejected links. First verification appeared at 35.843 seconds; the complete search and preliminary review took 85.906 seconds, with shortlist readiness at 85.891 seconds.

One preliminary recommendation was returned. Full assessment took 49.187 seconds and rated it a 48/100 worthwhile stretch, with missing financial-services/KYC evidence and unverified exact experience duration. This is weak evidence of coverage and usefulness, not a high-quality shortlist benchmark. Intake, planning and search used nine request reservations and three processing attempts; the full assessment added one of each. No employer form was filled or submitted.

Fixture tests establish routing, deduplication, reuse and connected UI behavior separately. Broader relevance, fair cold/warm speed comparisons and repeatable new-user throughput remain unproven.
