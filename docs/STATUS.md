# Current verification — 29 September 2026

[JobLazy 0.1.0-rc.2](https://github.com/Welzikl/JobLazy/releases/tag/v0.1.0-rc.2) is published as a private Windows prerelease for friend testing.

## Exact download

- File: `JobLazy-0.1.0-rc.2-windows.zip` (929,138 bytes).
- SHA-256: `b7704609e308c3737e1d63452898cddf7a87cdfeb9b3f795847aaa82013ad450`.
- Tested source/tag: `b8ec944b5c3971e27ed6671fbeb3eed83c18bfb8` / `v0.1.0-rc.2`.
- Uploaded to GitHub, downloaded through the signed-in browser, and checked: SHA-256 matches the tested ZIP.
- Later changes on `main` improve documentation only; the release ZIP and source tag remain unchanged. Older status text inside the frozen ZIP predates final verification; use this page and the companion release report for final results.

## Windows verification

All **539 tests passed**, with zero failures and zero skips, in 487.579 seconds from a clean extraction of the exact ZIP. Setup created a new virtual environment, installed pinned dependencies, and passed prerequisite checks. The actual launcher served onboarding with HTTP 200, disclosed Luna, and started without a personal profile. Source hashes, private-data audit, vendor hashes/licenses and local documentation links passed.

This was an existing Windows development PC, not a fresh Windows VM or the friend's PC. The joined browser journey used model doubles, fictional candidate facts and a local employer form. It covered profile confirmation, six search missions, assessment, reviewed PDF, form preparation, confirmed answers, same-session continuation and recorded outcome. The attached CV was preserved and no form was submitted.

## Separate live Luna trial

Real Luna calls with a fictional candidate completed intake, planning, six scouts, preliminary review, selected-role assessment and CV generation. Search/review took 85.906 seconds: 18 leads, three duplicates, three verified postings, 12 rejected links and one preliminary recommendation. Full assessment rated that role a 48/100 stretch.

Manual CV inspection found unsupported authorship wording. Generation and cached-material validation were corrected, and live regeneration retained the supported original wording. The full trial including correction used 14 model request reservations and seven processing attempts. The corrected live runtime matches the packaged runtime. No real employer form was filled or submitted.

That is limited workflow evidence, not proof of broad search quality, employer-form coverage or 25 successful applications a day. The friend's account capacity is untested.

## Remote CI and remaining limits

Windows and Ubuntu workflows are published. The [initial source run](https://github.com/Welzikl/JobLazy/actions/runs/36592185967) had one Ubuntu failure in `test_misleading_conflicting_and_unrelated_receipts_stay_unknown`: a conflicting fixture receipt was classified as submitted instead of unknown. A [separate tag run of the same source](https://github.com/Welzikl/JobLazy/actions/runs/36592544143) passed Ubuntu. Windows jobs were still running at publication readback. Remote CI is therefore **not certified green**.

The receipt reader enumerates elements and reads their text in separate browser calls, which can observe a changing page inconsistently. This is an unresolved intermittent receipt-observation issue in the automated submission test path. The friend workflow leaves final submission and outcome recording to the user. Do not interpret the passing local suite or the separate Ubuntu pass as resolving this issue.

Check [GitHub Actions](https://github.com/Welzikl/JobLazy/actions) for later results. The exact-ZIP 539-test result above remains separate local Windows evidence.

Final Submit remains manual. Employer forms vary; scanned CVs need readable text; supporting-link content attribution is unfinished. Employer replies and LinkedIn outreach are outside this release. Review every generated CV and employer field.

[Full release verification report](RELEASE-VERIFICATION.md) · [Features](FEATURES.md) · [Windows help](WINDOWS-QUICKSTART.md) · [Usage](ECONOMICAL-USAGE.md)
