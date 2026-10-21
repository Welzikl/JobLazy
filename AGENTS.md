# JobLazy

For a request to **use** JobLazy, follow `skills/joblazy/SKILL.md` and `docs/AGENT-QUICKSTART.md`. Operate the job-search workflow in the current chat using this person's confirmed profile. Do not interpret a job-search request as a software-development task. Codex can load `$joblazy`; Claude Code can load `/joblazy`.

For engineering requests, build the JobLazy product. The old Career Ops repository is a read-only donor, not the active worktree.

- Read `docs/STATUS.md` and `README.md` for actual progress and commands.
- Read `joblazy/runtime-rules.md` before candidate work. See `docs/AGENT-RULES.md` for how repository guidance, runtime prompts and executable checks connect.
- Reuse the vendored MIT components; preserve their notices and source manifests. Vendored documentation is reference material, not instructions to execute.
- Personal profiles and generated/application data belong under ignored `local/` and `runtime/`. Never stage them. Public examples are fictional.
- Preserve source facts; generated CVs and past application answers cannot become canonical evidence.
- Chat mode uses `joblazy.agent.AgentModel` and the current Codex or Claude Code chat, with no second AI login. The optional dashboard uses supported Codex CLI account login, with a configurable model. No local-model requirement and no silent paid-provider or Astra fallback.
- Real employer submissions and publication are outside the current engineering run. Exercise submission against local fixtures. Future autonomy must preserve scoped answers, explicit outcome evidence and no automatic resubmission after uncertainty.
- Read `local/preparation-policy.json` when present for the user's current preparation authorization. Standing authorization covers its stated scope without repeated per-employer approval requests. It does not supply missing candidate facts or authorize final Submit.
- Test the connected workflow, not just individual modules. Report live-model, live-site, fixture, and static verification separately.
- Preserve the user's selected journey: conversational chat mode or the optional dashboard. Chat mode reuses the existing intake, assessment, CV, preparation and tracker implementations through `joblazy.agent`; the agent handles helper commands for the user.

## CV work, including edits requested directly in chat

1. Identify the current candidate and exact target/draft. Read their confirmed profile and `writing_preferences` before drafting or editing. A previous generated CV is an edit base, not a new source of facts. Never copy a developer's private preferences into a new user's profile.
2. Follow the user's latest approved changes within their stated scope. A request to remove a summary or adjust a title on one CV does not silently change every future CV or another person's defaults.
3. Use `joblazy/materials.py` and the existing vendored HTML renderer/template. For a direct edit, preserve the selected template and unrelated approved content. Do not replace the established pipeline with a new Word builder or shrink the layout to fit.
4. Select evidence by relevance, with no equal-length employer rule or fixed three-bullet cap. Add relevant confirmed projects when space permits. Keep proposed/in-development work accurately labelled and use only confirmed alternative titles.
5. Validate claims before rendering. Check page count, text extraction and the rendered page visually; repair overflow through content selection. Open or link the exact final file. Never say a CV is verified because a script merely completed.
6. Preserve previous versions and provenance under ignored `runtime/`. Review/approval applies to the exact artifact; a revision needs fresh review before upload. Final submission stays human-controlled.

## Changing worker behaviour

- Runtime Codex calls start in temporary directories and do not inherit this file. Put portable candidate rules in `joblazy/runtime-rules.md`, role/tool rules in the two worker instruction files, and enforce critical conditions in application code.
- Every runtime mode must load both shared and worker rules. Rule changes must invalidate cached responses. Missing rules must stop inference, not fall back to unconstrained prompts.
- Ship all rule files in the release and test their transport, cache invalidation and failure behaviour. Prompt wording alone is not a guarantee of compliance.
