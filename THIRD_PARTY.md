# Reused components

## python-phonenumbers / phonenumberslite

Dependency: `phonenumberslite==9.0.34`, installed from the published wheel through the pinned Python requirements. Upstream: https://github.com/daviddrysdale/python-phonenumbers; release: https://pypi.org/project/phonenumberslite/9.0.34/. This Python port of Google's libphonenumber retains its Apache-2.0 license in the package distribution; it is not relicensed as JobLazy code. No library source is copied into the vendor snapshots.

JobLazy uses its offline parsing, validation, region metadata and national-number formatting. Ambiguous shared calling codes do not establish a phone region. Phone-derived routing is never candidate residence, work authorization or citizenship. The lite distribution omits geocoder/carrier/timezone datasets that this workflow does not need.

## Personal-JobPilot

Source: https://github.com/TheCromazone/Personal-JobPilot

Pinned commit: `a582c29d0f1aed97b93b13d843671487ab8c25d3`.

MIT, Copyright (c) 2026 Matthew Cromaz. Original license: `vendor/personal-jobpilot/LICENSE`. The source manifest lists the original Git blob hashes, verified when retrieved. The active integrations use `agents/autofill_mapper.py` and `browser-extension/content/scan.js` / `fill.js`. Only these components, the license, and the upstream README are vendored; no upstream service or scheduler is launched.

JobLazy wraps mapping so upstream personal defaults cannot supply unknown candidate answers. JobLazy owns queue transitions and submission verification rather than using the upstream redirect/form-disappearance success heuristic.

## Career Ops

Source: the user-authorized local Career Ops adaptation, originally https://github.com/santifer/career-ops.

MIT, Copyright (c) 2026 Santiago Fernández de Valderrama. Original license: `vendor/career-ops/LICENSE`. Reuses the HTML renderer, section helper, user-selected template, ATS/broad-feed providers, HTTP helper, DNS cache and user-agent constants. Visible-JD extraction is adapted from `browser-extract.mjs`. Copied-file SHA-256 values are recorded separately. The source worktree was dirty, so its HEAD alone does not identify these file contents.

No personal CV, targeting file, application record or credential is included in the vendor snapshot.

JobLazy's `scripts/ashby.mjs` is a small MIT-licensed derivative of the retained Ashby provider. It adds support for Ashby's nested salary summary component while keeping the complete upstream file intact under `vendor/`; its attribution is retained here and in the file header.

The Amazon/AWS public-search provider was subsequently copied verbatim from the same local donor and added to the existing SHA-256 manifest. JobLazy's wrapper preserves separately supplied qualifications and location-country associations, normalizes calendar posting dates, and reports incomplete result counts. The retained upstream file and license are unchanged.

The SmartRecruiters public-posting provider was also copied verbatim from that donor and added to the same manifest. JobLazy supplies the city/country query filters, exact-identity detail retrieval, full-description preservation and source warnings around it. Spotify uses the already retained Lever provider; JobLazy preserves its secondary locations and closing conditions. These integrations retain the original license and provider hashes.
