# Changelog

User-visible changes to N3MemoryCore Free for Codex.

## [1.9.2] - 2026-11-28

- Retain usable search hits and supplementary evidence when part of a response is malformed. Refine the ranking of weak matches with evidence from separate conversation turns.
- Handle malformed UTF-8 input, explicit empty agent labels, large conversation recall, and invalid re-embedding checkpoints cleanly.
- Recover from model-name lookup failures using a complete local model cache and scope model-load retry delays to the failing model.
- Clarify hook installation, trust, and troubleshooting when the Codex desktop hook list is empty. Document the isolated acceptance and cross-session checks.

## [1.9.1] - 2026-11-25

- Dedicated Python package, commands, data root, and port for side-by-side use with the original Free edition.
- Codex prompt and Stop hooks with host IDs, local audit records, suppression of opted-out or detected-secret turns, and manual hook trust.
- Optional search and eligible conversation writes to a verified original Free or Pro server. The Codex client keeps a local audit trail in connected mode.
- The instruction documents are v1.9.1 (`N3MemoryCore_v1.9.1_Free_EN.md`, `N3MemoryCore_v1.9.1_Free_JP.md`).

## [1.9.0] - 2026-11-18

- Codex `UserPromptSubmit` and `Stop` hooks capture prompts and final replies with the same turn ID.
- Hybrid vector and FTS retrieval, session-aware ranking and local SQLite storage.
- Index metadata, repair and resumable re-embedding support.
- Safer hook save failure reporting, index repair and provenance consistency.
- Documentation for WAL-safe backup and `N3MC_HOME` configuration.

For historical changes to earlier versions, see the repository's Git history.
