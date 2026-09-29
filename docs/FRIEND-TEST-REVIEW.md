# Friend-test release review

29 September 2026. Candidate: 0.1.0-rc.1. This review describes the current implementation, not a completed published release.

## Findings addressed

- Friend routing now uses GPT-6 Luna for intake, planning, six search missions, preliminary review, full assessment, CV generation and assisted preparation/resume. Personal defaults remain unchanged.
- Model reservations and processing attempts are shared through the durable ledger. Central atomic limits stop attempts above 25 and uncached request reservations above 50 per UTC day.
- The application UI connects selection, assessment, CV generation, exact PDF review, employer-form preparation, confirmed answers, same-session resume and explicit outcome recording.
- Preparation forwards the reviewed CV hash to the child process and rechecks the profile/checkpoint under the shared lock. Changed material is not silently regenerated and uploaded.
- Live browser commands have session identities, fresh heartbeats and single-consumption behavior. Uncertain outcomes prevent automatic retry.
- Windows setup, dependency/browser preflight and a friend-only launcher are implemented. The first-run screen discloses Luna before CV extraction.

## Evidence inspected

- A broad disposable-source run executed 535 tests: 534 passed, one failed because the fictional candidate lived in Bristol but the fictional form offered only London/Manchester. The application correctly stopped on the unsupported location.
- The dedicated friend fixture was corrected to offer Bristol. The strengthened connected journey plus allowance/application/dashboard checks then passed all 18 tests in 28.457 seconds.
- That journey covers CV intake, confirmation, six Luna scout doubles, Luna batch review, selected assessment, PDF generation/review, form preparation, confirmed-answer save, live resume and outcome recording. It verifies the answer reached the form, preparation completed, the original attached File object remained, and no submission occurred.
- Setup created a fresh virtual environment and installed pinned dependencies in a clean source directory on the existing Windows development host. Launcher smoke returned HTTP 200, displayed Luna and preserved an absent personal profile.
- Screenshots show the actual UI with fictional data. They do not establish live model quality.

Private logs remain outside the release. These checks predate the final downloadable artifact; they cannot certify its exact contents.

## Remaining release gates

1. Build an intentional source-only versioned ZIP with a manifest/checksum and inspect its exact contents, including retained licenses.
2. Extract that ZIP into a fresh Windows directory, audit before setup, install, launch and run the complete regression and joined fixture journey against those exact files.
3. Run bounded live Luna checks with fictional candidate data. Measure elapsed time, requests and useful verified recommendations separately from fixture performance. Login alone does not prove model access or subscription capacity.
4. Resolve GitHub owner and visibility, publish the audited repository/download, and read back external state. The Windows app runs locally; GitHub Pages cannot serve its backend.
5. Verify the friend's own model access and first application preparation during her trial. No claim about her account's daily capacity can be made from this host alone.

## Product limitations

ATS coverage and form behavior vary. Supporting-link content attribution is unfinished. Image-only CVs need text. Final Submit stays manual. Email replies and LinkedIn outreach are later work. The local 25-attempt ceiling is not a throughput guarantee.

## Subsequent exact-artifact and live checks

The first ZIP (0.1.0-rc.1) passed all 535 tests in 484.888 seconds from a clean Windows extraction with newly installed dependencies. Its manifest verified all 256 source files; the private-profile audit and all 33 vendor files/licenses passed. Its actual launcher passed the blank-profile HTTP smoke test.

A live Luna-only fictional trial completed intake (8.875s), planning (12.203s), six-mission search/review (85.906s), one full assessment (49.187s) and local CV generation (19.328s). It used 12 uncached request reservations and five processing attempts. Three postings were verified; one preliminary recommendation became a 48/100 worthwhile stretch. This limited yield does not establish strong general relevance. No real employer form was filled or submitted.

Manual CV inspection found an unsupported change from using a checklist to creating it. The next candidate adds a conservative authorship check during generation and cached-material reuse, plus explicit UI retry for invalidated material/technical failures. The original trial artifacts are preserved privately. Focused claim tests passed 41 checks, cache/review/export tests passed 21, and application controls passed five. Final extraction results are recorded separately for the actual download; the first ZIP's full-suite result does not certify changed runtime code.
