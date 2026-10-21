# Try JobLazy on Windows

This is an early-access local application. The friend launcher uses GPT-6 Luna throughout and has no Astra fallback. Your account allowance still applies; 25 processing attempts is a ceiling, not a promise of 25 completed applications.

## Set up once

1. Install Python 3.12 or later (include the Python launcher), Node.js 22 or later, and Edge or Chrome. Install Codex and sign in with your own account using the [official quickstart](https://learn.chatgpt.com/docs/quickstart).
2. [Download the tested dashboard Windows ZIP](https://github.com/Welzikl/JobLazy/releases/download/v0.1.0-rc.2/JobLazy-0.1.0-rc.2-windows.zip). Extract it completely into a folder you can write to. Do not run it from inside the ZIP. For Codex or Claude Code chat mode, use the current repository and the [chat quickstart](AGENT-QUICKSTART.md) instead.
3. Double-click **Setup.cmd**. It creates a local `.venv`, installs the pinned Python dependencies and checks prerequisites. It does not install system programs or purchase credits. Internet access is needed for dependency downloads.
4. Double-click **Start JobLazy.cmd**. Keep its window open while using JobLazy. This always starts the friend preset and selects Edge or Chrome automatically.

No Python, Node, Codex credentials or candidate data are bundled in the download. Setup does not copy anyone else's profile. If setup fails, read its message, fix the missing prerequisite and run it again.

## Use the app

Upload a text-readable PDF, DOCX or text CV. Review and correct the extracted facts, answer follow-ups and describe the work you want next. Confirm the profile before searching.

Build and save your search plan. **Search and review** runs six Luna missions and shows a preliminary shortlist. Open **Review this application** for a role you want to pursue. **Select and assess this role** runs the full assessment. Generate the tailored CV, open the PDF, and confirm that you reviewed it before selecting **Prepare employer form**.

The employer form opens in a separate browser. JobLazy does not click Submit. Use the application screen to save your own answers and **Continue in the open form**. Handle employer sign-in in the employer browser. Review all fields yourself before any manual submission.

Record **submitted**, **not submitted**, or **uncertain** with a note about what you checked. An uncertain outcome stays protected from automatic retry. Download the tracker from the main dashboard whenever needed.

## If something stops

- **Codex not signed in:** use Connect Codex and finish sign-in in the window it opens.
- **Luna unavailable or allowance exhausted:** check your account's model access and usage/reset display. Saved work remains available. JobLazy does not switch to Astra or buy credits.
- **Processing allowance reached:** new attempts stop until the next UTC day. Reusing an existing valid CV does not require a fresh generation call.
- **Resume unavailable:** check whether the employer browser is still open. A closed or expired session cannot resume a different form. Record the checked outcome before retrying.
- **Profile or CV changed:** regenerate if needed and review the current PDF again. JobLazy will not replace a confirmed CV silently during preparation.
- **Another operation is active:** wait for it to finish. Avoid running two copies against the same data folder.
- **Port already in use:** close the other JobLazy launcher window before restarting.
- **Image-only CV:** supply a text-readable copy; OCR is not currently built in.

Your profile, uploaded sources, CVs, queue, model cache and browser session are kept in `local/` and `runtime/` on your computer. Relevant text is sent through your Codex account for model tasks; local storage does not mean offline inference. Do not attach those folders or raw logs to a public bug report.

For feedback, report the step, expected/actual behavior and a screenshot with personal information removed. The [bug report template](../.github/ISSUE_TEMPLATE/bug_report.md) lists what to include.
