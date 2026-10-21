# The JobLazy casebook

[Back to JobLazy](../README.md)

This is the work behind the project: finding opportunities, preparing them carefully, remembering what was sent and using that evidence at the next stage. The prompts below are paraphrased examples, not transcripts. Candidate details, employer identifiers, private documents and receipts are intentionally omitted.

**Built-in** means JobLazy has local code for that part of the workflow. **Agent-assisted** means the accompanying agent works with saved evidence and its available tools. Earlier personal sessions establish that the work happened; they do not prove that every task is an automated feature in this release.

## 1. Turn a CV into a reusable, confirmed profile

> “Here's my CV. Help me work out which roles to target.”

**Built-in intake, with confirmation in chat.** Read the source CV, separate past experience from desired future work, identify gaps and ask the person to confirm the important details. A draft stays a draft until confirmed.

**Keep:** the untouched original, a confirmed profile, targeting preferences and unanswered questions. A new user starts from their own evidence; they do not inherit the developer's career history or preferences.

## 2. Search broadly, then check the actual role

> “Find relevant jobs, including ones I might miss by searching only my current title.”

**Built-in source readers and assessment; host-assisted web discovery in chat.** Our search work combined target roles, adjacent responsibilities, employers, ATS boards, sector themes and a gap-filling pass. Open the employer posting, capture its description and source, remove duplicates, and explain why a role is relevant.

**Keep:** a source-backed shortlist with fit reasons, uncertainties and inaccessible sources clearly identified. A search-result snippet or an old saved URL is not enough to say a vacancy is open. Search coverage and quality still need judgment.

## 3. Make a different CV for a different opportunity

> “Tailor this for a partnerships role. Then do the business-development role separately.”

**Built-in assessment and materials pipeline.** Earlier work produced distinct CVs for commercial, partnerships, business-development and revenue-operations roles. Each version chose evidence relevant to that role rather than changing the candidate's underlying history.

**Keep:** the job description, assessment and role-linked PDF. Claims about metrics, dates, ownership and responsibilities must trace to confirmed evidence. A generated bullet cannot become a new source fact.

## 4. Edit the CV without rebuilding it from scratch

> “Remove the summary from this version and give the relevant project more space.”

**Agent-assisted revision using the existing materials workflow.** Apply the requested change to the selected draft, preserve the approved template and unrelated content, and check both extracted text and rendered pages. Fit content through relevance rather than shrinking the layout.

**Keep:** the previous version and the revised PDF. An edit to one application does not silently change every future CV or the person's global preferences. Any revised upload needs review of that exact file.

## 5. Prepare an application with the reviewed materials

> “Use this CV and help me complete the application.”

**Built-in assisted preparation.** The workflow binds preparation to the reviewed PDF, fills supported fields from confirmed answers and pauses when information is missing. Earlier application work retained upload and outcome evidence alongside each role.

**Keep:** the exact reviewed document, recorded answers, preparation evidence and a browser handoff. The user makes the final submission. A prepared form is not a submitted application; uncertainty must be resolved before a retry. Current connected form checks use fictional/local fixtures, not a certification of every employer site.

## 6. Recover the exact CV that was sent

> “Which CV did I use for that Commercial Associate application?”

**Agent-assisted retrieval of saved JobLazy evidence.** Several applications can exist at one employer. In our actual retrieval work, we identified the correct role, inspected its upload and artifact records, and matched file hashes rather than choosing the newest or similarly named PDF. We also distinguished separate partnerships and business-development CVs at another employer.

**Keep:** the exact role-linked CV and an explanation of how it was matched. If upload/receipt evidence is missing, say what can and cannot be established. A form inventory alone does not prove submission.

## 7. See every saved opportunity in one place

> “Give me one spreadsheet showing every opportunity and what's happened.”

**Built-in tracker and export.** We added an Excel-ready CSV view over the same saved job records: company, role, location, source, status, fit reason, posting link, timestamps, latest event and outcome note.

**Keep:** one canonical local tracker and a shareable/exportable snapshot. The export covers records saved in that workspace, not every application made elsewhere. Employer replies require evidence to be added; an earlier Gmail reconciliation attempt was blocked and did not synchronize the inbox.

## 8. Prepare for the interview using the actual application

> “I've got an interview for the Commercial Associate role. Help me prepare.”

**Agent-assisted.** We retrieved the role-specific CV and researched official company sources, then produced a brief with a 60-second introduction, company motivation, evidence-based stories, likely questions, questions to ask, a territory-plan structure and role-play guidance.

**Keep:** an interview pack tied to the actual role and evidence. Company facts, candidate experience and proposed answers stay distinguishable. The brief explicitly avoided presenting unverified enterprise-closing or quota experience as fact.

## 9. Research the company or build a territory argument

> “Help me understand this company and explain which accounts I would prioritize.”

**Agent-assisted, with research and spreadsheet/presentation tools.** Related career work included official-source company research, territory shortlists, evidence columns and presentation revisions following stakeholder feedback. Research needed a visible source and a clear distinction between facts, inferences and missing coverage.

**Keep:** a sourced brief, editable research workbook or presentation, depending on the task. Preserve the original artifact and agreed scoring logic. Partial research must remain labelled partial; JobLazy does not ship an automatic territory-scoring engine.

## 10. Draft an outreach message that sounds like you

> “Ask someone for interview advice, but make it less asky.”

**Agent-assisted drafting.** We refined a warm message around brief context, appreciation and one modest request, with an optional short conversation. This was message drafting and refinement, not an automated outreach campaign.

**Keep:** copy you can review and send yourself. Recipient choice, tone and permission to send remain separate decisions. JobLazy does not automatically send emails or LinkedIn messages.

## 11. Complete a questionnaire from confirmed answers

> “Fill this questionnaire using the answers I've given you. Keep the original.”

**Agent-assisted, with document tools.** In one completed task, a separate DOCX copy had 15 applicant fields filled from confirmed answers. The original questions, body and business section were preserved and checked against the source.

**Keep:** the original, an editable completed copy and a short list of anything unresolved. Sensitive identity or legal answers come from the person, not assumptions from a CV. This is document assistance, not a dedicated questionnaire feature.

## 12. Turn work evidence into something worth showing

> “Use these project documents to make a portfolio for this opportunity.”

**Agent-assisted, with document and presentation tools.** Earlier portfolio work turned source material into an audience-specific eight-slide core deck plus appendix, an editable presentation, a shareable PDF and a design pack. The narrative selected relevant work and retained original source assets.

**Keep:** a presentation grounded in documented work, with proposals clearly labelled as proposals. Do not invent seniority, shipped systems, authorship or business impact. JobLazy's CV pipeline does not automatically generate these decks.

## Start your own version of this workflow

Open a fresh JobLazy folder in Codex or Claude Code and say:

> Use JobLazy in this chat. Read skills/joblazy/SKILL.md. Here's my CV and the kind of work I want next. Help me confirm my profile, find relevant roles, and keep track of what we do.

The [chat quickstart](AGENT-QUICKSTART.md) explains setup. The [feature inventory](FEATURES.md) maps shipped capabilities to code. The [verification report](AGENT-VERIFICATION.md) distinguishes local tests from live operation.
