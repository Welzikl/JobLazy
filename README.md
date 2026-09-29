# JobLazy

Find jobs, review a factual tailored CV, and prepare employer forms using your own Codex account. You always control the final **Submit** action.

**Windows friend-test candidate · Luna only · local application**

This is early-access software. The complete browser journey has passed with fictional models and local employer forms. One bounded live Luna trial exercised intake, search, assessment and CV generation. Broader recommendation quality, varied employer forms and the friend's actual account capacity remain unproven. Download the versioned Windows ZIP from GitHub Releases when available; check its accompanying verification report.

## Start on Windows

1. Install **Python 3.12+**, **Node.js 22+**, and **Edge or Chrome**. Install Codex and sign in using the [official quickstart](https://learn.chatgpt.com/docs/quickstart).
2. Extract the release ZIP completely into a writable folder.
3. Double-click **Setup.cmd**. It installs pinned Python dependencies into this folder and checks prerequisites.
4. Double-click **Start JobLazy.cmd**. Keep its window open while using the app.

The launcher always selects the **friend preset**, using GPT-6 Luna for onboarding, search planning, six search missions, preliminary review, full assessment, CV generation and application preparation. There is no Astra dependency, model fallback or API key requirement. A successful Codex login does not establish Luna availability or remaining allowance.

[Windows instructions and troubleshooting](docs/WINDOWS-QUICKSTART.md) · [Feature inventory](docs/FEATURES.md) · [Usage and limits](docs/ECONOMICAL-USAGE.md)

## From CV to application

| Step | What happens |
| --- | --- |
| Upload and confirm | Import a text-readable PDF, DOCX or text CV. Correct the draft, answer follow-ups and confirm facts and future-work preferences. |
| Search | Review an editable search plan. Run six complementary Luna missions, with up to three model workers concurrently, plus direct ATS reads and supplementary feeds. |
| Select and assess | Inspect preliminary recommendations, select a role, then request its full evidence-based assessment. |
| Review your CV | Generate materials for a selected role, open the PDF and confirm the exact version before preparation. |
| Prepare the form | A separate employer browser opens. Supported fields and the reviewed CV are filled; unknown answers remain for you. |
| Resolve questions | Save confirmed answers in the application screen and explicitly continue in the same open form. |
| Record the outcome | Review and submit manually if you choose. Record submitted, not submitted or uncertain, with a note about what you checked. Export the tracker as CSV. |

No terminal commands are required during this normal workflow. Setup and launch use visible Windows command windows. Saving a draft, preparing a form and recording a submission are separate states; an uncertain outcome blocks automatic retry.

<details>
<summary>Search screen — fictional test data</summary>

![JobLazy search interface with fictional test data](docs/screenshots/search.png)

</details>

<details>
<summary>Application screen — fictional test data</summary>

![JobLazy application review and question controls](docs/screenshots/application.png)

</details>

These screenshots come from the actual interface running with fictional candidate facts, model doubles and a local employer fixture. They do not demonstrate live recommendation quality.

## Keep usage economical

Saved results open without a new search. Every explicitly started new web search dispatches six bounded Luna missions; interrupted runs resume unfinished missions. Public ATS retrieval, filtering, deduplication, PDF rendering and tracking use ordinary code. Preliminary reviews use compact batches, and validated assessments and materials can be reused while their evidence remains current.

Shared local safeguards allow at most **25 processing attempts** and **50 uncached model-request reservations per UTC day**, including assisted preparation and resume. An attempt may be an assessment or preparation step. These limits are not a promise of 25 applications, an account allowance estimate or a substitute for Codex limits. Other Codex use shares your account capacity.

## Data and network access

Your profile, uploaded CV, confirmed answers, generated documents, job history, model cache and employer browser session stay under ignored `local/` and `runtime/` folders. Relevant text is sent through your own Codex account for AI tasks. Job discovery contacts public job sources; preparation contacts the employer site. Local storage does not mean offline processing.

Never publish these private folders or raw logs. JobLazy binds its interface to loopback and protects API and document access with a local token. It does not retrieve employer email replies or contact people on LinkedIn.

## Known limits

- ATS coverage is partial and employer forms change. Broad real-site reliability is unproven.
- Image-only CVs need a text-readable copy. Portfolio links can be recorded; their content is not automatically established as candidate evidence.
- Preliminary recommendations require a full assessment before preparation. Review every generated CV and every employer field.
- Account/model failures stop without switching models. Saved progress remains, but a closed employer browser cannot resume its old live session.
- This Python application runs on your PC. GitHub hosts source and downloads; GitHub Pages cannot run the backend.

See [current verification](docs/STATUS.md) and [release findings](docs/FRIEND-TEST-REVIEW.md).

## Developer use

The Windows launcher handles normal friend use. For an existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m joblazy dashboard --preset friend --browser-channel msedge
```

Plain `dashboard` retains the original personal preset: Luna search, Astra review/assessment and Terra intake/preparation. Existing personal data is not migrated or replaced by selecting the friend preset. See [operations](docs/OPERATIONS.md), [profile setup](docs/PROFILE.md) and [search behavior](docs/SEARCH.md).

Run verification in a disposable source-only copy so tests cannot affect your private working data:

```powershell
.\.venv\Scripts\python.exe scripts\verify-vendor.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

Run `python scripts/check-public.py --source-tree` on a clean extraction **before** setup creates private/generated directories; use `python scripts/check-public.py` for a Git checkout. Some legacy browser tests require Chrome. The fictional connected friend journey also supports Edge via `JOBLAZY_TEST_BROWSER_CHANNEL=msedge`. Windows and Ubuntu CI are configured; a configured workflow is not evidence of a completed remote run.

`joblazy/` contains the local server and workflow, `scripts/` provides setup and source adapters, `tests/` contains regression and fictional browser fixtures, and `vendor/` retains upstream components and provenance manifests.

[MIT License](LICENSE) · [Third-party licenses and source manifests](THIRD_PARTY.md) · [Redacted bug-report template](.github/ISSUE_TEMPLATE/bug_report.md)

