# Current verification — 29 September 2026

JobLazy 0.1.0-rc.1 is a Windows friend-test candidate. It is not yet a published or fully verified release.

## Implemented

The friend preset uses Luna throughout and preserves personal defaults. Six complementary search missions run with bounded concurrency. Selected-role assessment, reviewed CV generation, employer-form preparation, confirmed answers, same-session resume and outcome recording are connected to the browser interface. Shared local safeguards enforce 25 processing attempts and 50 uncached model-request reservations per UTC day, including assisted work. Setup and launch scripts check prerequisites and select the friend preset.

## Evidence

- Disposable-source full suite: 535 tests, 534 passed and one fictional form-location mismatch. The fixture was corrected to accept the fictional candidate's city.
- Corrected connected friend journey plus allowance/application/dashboard regressions: 18 passed in 28.457 seconds. The answer reached the form, the form was prepared, the original CV attachment was retained and no submission occurred.
- Clean-directory Windows setup installed pinned dependencies into a new virtual environment. The actual launcher served HTTP 200, disclosed Luna and started without a personal profile.
- These tests use model doubles and local employer forms. They establish the connected implementation, not live Luna quality, actual account capacity or broad employer-site reliability.

Exact ZIP extraction/testing, bounded live Luna checks and GitHub publication/readback remain. Windows and Ubuntu CI are configured but have not run remotely for this candidate.

See [feature inventory](FEATURES.md), [release findings](FRIEND-TEST-REVIEW.md), [usage](ECONOMICAL-USAGE.md) and [Windows instructions](WINDOWS-QUICKSTART.md). Older engineering observations in this development checkout are historical and are excluded from the friend download.

## Later candidate checks

The exact 0.1.0-rc.1 ZIP passed all 535 tests in 484.888 seconds, plus manifest/audit/setup/launch checks. A bounded live Luna trial completed all stages through a local PDF, with 12 requests and five processing attempts, and no real employer form actions. Its one recommendation assessed as a 48/100 stretch. Manual inspection exposed an unsupported authorship paraphrase; the next candidate adds generation/cache guards and explicit UI recovery. Focused regressions pass. Consult the verification report shipped alongside the final download for its exact hash and test results.
