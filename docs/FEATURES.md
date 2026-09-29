# JobLazy feature inventory

Reviewed 29 September 2026 against the friend-test candidate. Implementation and fixture evidence do not establish reliability on every employer site.

| Feature | Current behavior | Evidence or limitation |
| --- | --- | --- |
| Windows setup and launch | Setup.cmd installs pinned dependencies; Start JobLazy.cmd detects Edge/Chrome and always selects the friend preset. | Fresh-directory setup and launcher smoke passed on the development Windows host. Exact ZIP verification remains a release gate. |
| Luna-only friend preset | Luna handles intake, planning, six scouts, both assessment stages, materials and preparation/resume. No model fallback. | Routing checked in connected fixtures. Original personal Luna/Astra/Terra preset preserved. |
| CV intake | PDF, DOCX and text extraction produces an editable draft with follow-ups and explicit confirmation. | Browser regression; scanned documents require readable text. |
| Resumable onboarding and profile correction | Drafts autosave; revisions reject stale updates. Confirmed facts, user edits and undisplayed canonical fields are preserved. | Connected and profile-preservation regression coverage. Portfolio content attribution remains unfinished. |
| Future-work preferences | Desired direction, location, work arrangement, level and exclusions are separate from career evidence. | New profiles do not inherit the developer's employer list. Live career-change usefulness remains unproven. |
| Search plan | User reviews and saves title phrases and source choices before searching. | Browser flow covered. |
| Six Luna search missions | Every new delegated web search starts six complementary missions with at most three concurrent model workers. | Six dispatches asserted in the joined journey. Explicit interrupted-run resume reuses completed missions. Feed-only actions are distinct. |
| Direct ATS and feeds | Ashby, Greenhouse and Lever public posting reads, verified board registry, bounded expansion, supplementary public feeds and failure reporting. | Partial market coverage. Source access and relevance vary. |
| Deduplication and caching | Exact identities/verified aliases, title/location filtering, source caches and evidence-bound review reuse. | Regression coverage; saved records are not automatically fresh vacancies. |
| Preliminary shortlist | Compact Luna batch review with reasons, posting evidence and caveats. | Separate from a full assessment. Live Luna-only quality and latency need measurement. |
| Selected-role assessment | A visible action selects the role and requests a full grounded fit assessment. | Connected fictional journey passes; valid complete assessments can be reused. |
| Tailored CV review | Materials generated only for selected roles, validated against confirmed facts, opened as a PDF and confirmed by exact hash. | Connected fixture verifies the same reviewed file reaches the form. |
| Assisted preparation | Visible employer browser fills supported confirmed fields and attaches the reviewed CV. | Fictional form passes. Final Submit stays manual; broad real-site reliability unproven. |
| Questions and live resume | Application screen saves explicitly confirmed answers and resumes only its current live browser session. | Fixture verifies the answer reached the form and the original attachment remained. Stale/duplicate commands rejected. |
| Outcomes and history | UI records submitted/not-submitted/uncertain with a note. Uncertainty protects against automatic retry. | Regression coverage; a local record alone is not employer acceptance. |
| Tracker | CSV export of durable jobs, states, reasons and recorded outcomes. | No employer-email synchronization. |
| Shared allowances | Central 25-processing-attempt ceiling and 50 uncached model-request reservations per UTC day, including assist/resume. | Atomic reservation and boundary tests. Account capacity is separate and unknown. |
| Local UI protection | Loopback binding, local token, Host/Origin checks and verified CV serving. | Focused regression coverage; not a general security certification. |
| Release controls | Source/private-data audit, vendor hashes and licenses, versioned packaging work and Windows/Ubuntu CI configuration. | Exact candidate extraction, live checks and publication remain acceptance gates. |

## Outside this milestone

Employer email replies and LinkedIn contact discovery/outreach are deferred. Automatic employer submission is not provided. No promise of 25 completed applications per day or proven all-day unattended operation is made.

## Implementation map

- Intake/profile: `onboarding.py`, `profile_edit.py`, `onboarding.html`, `profile.html`.
- Search: `search.py`, `search_coordinator.py`, `search_missions.py`, `ats_postings.py`, `ats_registry.py`, `shortlist_flow.py`, `shortlist_review.py`.
- Application screen: `application_ui.py`, `application.html`, `dashboard.py`.
- Materials/forms: `materials.py`, `pipeline.py`, `checkpoints.py`, `assist.py`, `assist_bridge.py`.
- Shared limits/history: `limits.py`, `store.py`, `model.py`, `worker.py`.

See [release review](FRIEND-TEST-REVIEW.md) for remaining acceptance gates.
