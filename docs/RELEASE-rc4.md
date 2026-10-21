# JobLazy 0.1.0-rc.4 — release verification

Verified 21 October 2026 on the Windows development PC. This refresh packages the direct Codex/Claude Code chat workflow, prominent original Career Ops ratings, the 12-case guide and the redesigned repository page.

## Clean-extraction verification

- **546 tests passed**, zero failures, zero skips, exit code 0, **538.047 seconds**.
- Built the source candidate, extracted it into a new folder, created a fresh virtual environment and installed pinned dependencies through `scripts/setup-windows.ps1 -AgentMode`. Prerequisite checks passed without checking a second AI login.
- Ran `.venv/Scripts/python.exe -m unittest discover -s tests -t . -v` inside the extraction, with `JOBLAZY_TEST_BROWSER_CHANNEL=msedge`. Some legacy checks also use installed Chrome.
- All 279 candidate source-file hashes remained unchanged after setup and the test run.
- Final package runtime, tests, setup scripts, dependency locks and vendor files are byte-for-byte identical to the tested extraction. Only documentation and handoff wording were finalized afterward. The final package has its own checked manifest and SHA-256 file.
- Source/private-data audit includes comparison with the developer's private profile values; those values are not copied into the package. Vendor hashes and retained licenses pass verification.
- README was processed through GitHub's Markdown renderer. Desktop and phone layouts, responsive SVG selection, text bounds and local documentation links were checked. The graphics are labelled fictional illustrations, not application screenshots or live jobs.

The checksum asset alongside the ZIP identifies the exact downloadable archive. The companion verification asset also records that hash; it is outside the ZIP to avoid a self-referential checksum.

## What to expect

Start with the extracted project's START HERE.txt and the [chat quickstart](AGENT-QUICKSTART.md). The agent uses the current chat account for reasoning. Local helpers need Python 3.12+, Node.js 22+ and Edge/Chrome. The original overall 0–100 job score and five evidence-backed dimensions are retained. The host chat instructions require displaying that breakdown.

Runtime code and tests are unchanged from rc.3. That earlier verification also included a real Codex chat-to-helper intake exchange with a fictional CV. This release run uses local/fictional fixtures and model doubles; it is not a new live-model or live-employer trial.

## Practical limits

Final employer submission stays human-controlled. The optional dashboard still uses its separate Codex CLI backend. Live Claude Code operation and a new user's machine/account are untested. Broad employer coverage and search quality remain unproven. See [historical verification](AGENT-VERIFICATION.md) and [known limitations](STATUS.md), including the unresolved receipt-observation issue. A passing fixture run does not resolve that intermittent issue. Remote CI status is separate and is not certified by this local report.

This is an early-access prerelease, not a certification of general production reliability. No candidate data, credentials or Git history are included in the release package.
