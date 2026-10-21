# Chat mode verification - 21 October 2026

Candidate: 0.1.0-rc.3. This page concerns direct operation inside Codex or Claude Code; the earlier rc.2 dashboard release remains unchanged.

Chat mode uses `AgentModel` to exchange hash-bound requests and responses with the current chat. It does not invoke another AI CLI. The existing intake/confirmation, ranking, claim checks, renderer, checkpoints, preparation and SQLite tracker remain the implementation behind the workflow. Setup can check local dependencies without requiring a Codex login.

Five focused host-chat tests passed on the Windows development PC. They cover response/input/rule binding, schema rejection, missing rules, profile confirmation and overwrite protection, the real CV renderer/checkpoint with fictional host answers, invented-metric rejection, and a preflight that forbids construction of a Codex model. The connected fixture also checks the reviewed CV hash, exact attachment, durable manual handoff and tracker export.

The source package audit excludes local/runtime data and checks the developer's private profile values without copying that profile into the archive. Retained vendor hashes and licenses are checked by the release builder. Both native skill entrypoints and the shared skill pass the skill frontmatter validator.

The complete suite passed from a fresh rc.3 extraction with newly installed pinned dependencies: **546 tests, zero failures, zero skips, exit code 0, 405.048 seconds**. Command: `.venv/Scripts/python.exe -m unittest discover -s tests -t . -v`, with `JOBLAZY_TEST_BROWSER_CHANNEL=msedge`; some legacy tests also use installed Chrome. Agent-mode setup passed without checking a Codex login. All 271 source-file hashes remained unchanged after setup and the suite.

A separate real handoff from the current Codex chat also passed: the extracted helper emitted a request for a fictional CV, this chat supplied the schema-conforming response, and the helper saved a draft without creating a confirmed profile. No nested model process or real candidate was involved. This establishes the actual chat/file exchange for intake, not a live Claude Code session or broad search quality.

Only this verification page and the status summary were updated after the full suite. The final handoff's runtime, tests and setup scripts are byte-for-byte identical to the tested extraction; its manifest and SHA-256 are checked again. The companion report beside the ZIP records that final artifact hash. Historical rc.2 evidence remains separate.

These are fictional/local checks, not a live Claude Code session, a fresh Windows VM, or Nick's account and hardware. Skill auto-discovery and available web/browser tools depend on his host. The explicit 'read skills/joblazy/SKILL.md' entrypoint is available if a shortcut is not discovered. Broad employer coverage and recommendation quality remain unproven. The older receipt-observation issue in STATUS.md is unchanged; final submission and outcome recording remain human-controlled.
