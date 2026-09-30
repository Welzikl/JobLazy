# How JobLazy loads agent rules

`AGENTS.md` guides coding agents opened at the repository root, including direct
CV edits. It is not automatically read by runtime workers: Codex calls start in
isolated temporary directories with user configuration ignored.

Every `CodexModel` and `CodexWebSearch` request therefore loads
`joblazy/runtime-rules.md` plus its worker instruction file. The exact combined
bytes are written to the request's temporary instruction file and their hash is
part of the saved request/cache key. Changing either rules file invalidates old
responses. Missing, empty or unreadable rules stop the call before cache replay,
account checks or request-budget reservation. Both compact and noncompact modes
load instructions and keep shell/apps disabled. Only the search worker enables
web search. The source release builder requires all three runtime files.

The shared rules cover candidate isolation, evidence, honest titles and project
status, relevant CV content allocation, the existing renderer and human final
submission. Personal writing preferences still come from the current profile in
the tailoring request; public rule files must not contain private candidate facts.
This change does not add a preference editor or change CV schemas/section defaults.
Unsupported preferences still need application/schema support, not merely a prompt.

These instructions improve consistency; they cannot guarantee model compliance.
Keep deterministic claim/title checks, PDF page/text checks, exact-artifact review
and human submission. Tests of prompt transport prove what was supplied, not that
a live model will always obey. Review the rendered PDF before using it.

Changes apply to new local requests. Existing distributed ZIPs do not update
themselves: rebuild and verify a new package before giving it to a friend.
