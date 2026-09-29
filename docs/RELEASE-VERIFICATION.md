# JobLazy 0.1.0-rc.2 — verification report

Verified 29 September 2026. **Exact local release candidate tested; source published to the private GitHub repository. The published ZIP was downloaded through GitHub and its SHA-256 matched the tested artifact.**

## Exact artifact

- File: `JobLazy-0.1.0-rc.2-windows.zip`
- Size: 929,138 bytes.
- SHA-256: `b7704609e308c3737e1d63452898cddf7a87cdfeb9b3f795847aaa82013ad450`
- Clean publication checkout commit: `b8ec944b5c3971e27ed6671fbeb3eed83c18bfb8` on `main`.
- 257 source files plus `RELEASE-MANIFEST.json`. No Git history, development journal, personal profile, CV, database, credentials or browser session is included. Existing local development history is preserved separately.

## Windows extraction and connected tests

The exact ZIP was extracted into a new folder. Every source SHA-256 matched its manifest. The source audit checked the original private profile values from outside the extraction and found no matches or secret-pattern failures. All 33 retained vendor files matched their manifests and both licenses were retained. Local documentation links passed.

Setup created a new virtual environment and installed the pinned dependency set. Preflight confirmed Python 3.12.14, Node 22.23.0, Edge and an existing Codex login. Setup was invoked with its explicit Python-executable option pointing at the available Python installation; it did not install system prerequisites.

The actual friend launcher started with an unused local port and `-NoOpen`, served onboarding with HTTP 200, disclosed GPT-6 Luna and kept the personal profile absent. The launcher process tree was stopped after the smoke check. Source hashes remained unchanged after installation.

Command run from the extracted directory:

```powershell
$env:JOBLAZY_TEST_BROWSER_CHANNEL = 'msedge'
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

**539 tests passed, zero failures, zero skips, exit code 0, in 487.579 seconds.** Some legacy tests also use installed Chrome.

The joined fictional browser journey covers intake/correction/confirmation, search planning, six Luna scout doubles and a batch reviewer, selected assessment, PDF generation and exact-CV review, employer-form preparation, confirmed-answer saving, same-session resume and outcome recording. It verifies the answer reached the form, the form became prepared, the original attached File object remained, and no submission occurred. Separate tests cover the shared 25-attempt/50-request ceilings, protected handoffs, stale sessions, factual claims, cached material validity and explicit retry.

This was a clean extraction and dependency environment on an existing Windows development PC. It was not a fresh Windows VM or the friend's PC. Windows/Ubuntu GitHub Actions are configured. Remote CI results are reported separately; the test result above is from the exact local Windows extraction.

## Bounded live Luna evidence

These were real Luna calls and public posting reads with a fictional candidate; no real employer form was filled or submitted.

| Stage | Observation |
| --- | --- |
| CV extraction | 8.875 seconds; facts and source quotes retained; no missing facts invented. |
| Search planning | 12.203 seconds; role phrases and London location derived from the fictional future-work brief. |
| Six-mission search and preliminary review | 85.906 seconds total; three-worker concurrency; all six missions completed; 18 leads, three duplicates, three verified postings, 12 rejected links and one preliminary recommendation. First verified posting at 35.843 seconds. |
| Full assessment | 49.187 seconds; one 48/100 worthwhile stretch, with missing KYC/financial-services evidence and uncertain exact experience duration disclosed. |
| Initial CV | Generated in 19.328 seconds, but manual inspection found unsupported authorship wording. It was retained as failed quality evidence, not accepted as final proof. |
| Corrected CV | A new generation/cache authorship guard rejects that wording. Explicit re-assessment reused its validated model result in 3.594 seconds; regeneration took 17.640 seconds and retained the original supported checklist wording. |

Across the complete trial including correction: **14 uncached request reservations and seven processing attempts**. The profile remained unchanged. The corrected live runtime matches every packaged runtime file byte for byte. The generated PDF was one page and its text was inspected; semantic accuracy still requires the user's review.

The search produced only one stretch recommendation. That is a small transport/workflow test and limited usefulness evidence, not proof of broad coverage or a strong general shortlist. No extrapolation to the friend's account capacity or 25 successful daily applications is justified.

## Requirement audit

| Requirement | Evidence/status |
| --- | --- |
| Luna throughout; personal preset retained | Preset/routing tests, joined fixture and live Luna stages pass. No fallback. |
| Six complementary bounded scouts and ATS/cache work | All six observed live; concurrency three; direct-source, deduplication and cache regressions pass. Market coverage remains partial. |
| Shared economical limits | Atomic ledger tests pass, including assist/resume. Local caps are not account entitlements. |
| Complete browser journey | Joined fictional new-user test passes through outcome recording; Windows launcher passes. |
| Factual provenance, edits/history and manual Submit | Preservation/revision/claim/checkpoint/uncertainty tests pass. Live authorship defect fixed and rechecked. No real submission. |
| Windows setup, checks and recovery | Exact extraction installed and launched; explicit retry and session checks pass. Friend hardware/account remain untested. |
| Repository page, versioned download and privacy/licenses | README, screenshots, features, setup/troubleshooting, feedback template, exact ZIP/checksum and clean local Git commit prepared. Source and tested tag are published in the private repository; the release ZIP was downloaded back and its SHA-256 matched. |
| Exact-release and bounded live verification | Exact ZIP full suite and joined fixture pass; live evidence is separately reported above. |

## Try locally

Install Python 3.12+, Node 22+, Edge or Chrome, and Codex with your own account. Extract the whole ZIP, double-click `Setup.cmd`, then `Start JobLazy.cmd`. Upload and confirm your own CV in the browser. Review every generated CV and employer field; final Submit remains manual.

## Publication and remaining limitations

The source is published at https://github.com/Welzikl/JobLazy as a private repository, with tag `v0.1.0-rc.2` targeting the source commit above. Download access requires repository access. The published ZIP was downloaded through the signed-in GitHub browser and its SHA-256 matched the tested artifact. Remote CI results are available in GitHub Actions and are separate from the local Windows result above. The GitHub page will host documentation and downloads; the app runs locally.

ATS/form behavior varies; scan-only PDFs need text; supporting-link content attribution is unfinished. Email replies and LinkedIn outreach are outside this milestone. The factual guard is conservative and supplements source validation and model review; it is not a guarantee that every paraphrase is correct.
