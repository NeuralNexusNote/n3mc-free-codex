# Changelog

User-visible changes to N3MemoryCore Free for Codex.

## [1.9.1] - 2026-11-25

- Dedicated Python package, commands, data root, and port for side-by-side use with the original Free edition.
- Codex prompt and Stop hooks with host IDs, local audit records, suppression of opted-out or detected-secret turns, and manual hook trust.
- Optional read-only search of a verified original Free server. Connected Codex conversation events stay in the local audit log.
- The instruction documents are v1.9.1 (`N3MemoryCore_v1.9.1_Free_EN.md`, `N3MemoryCore_v1.9.1_Free_JP.md`).

## [1.9.0] - 2026-11-18

- Codex `UserPromptSubmit` and `Stop` hooks capture prompts and final replies with the same turn ID.
- Hybrid vector and FTS retrieval, session-aware ranking and local SQLite storage.
- Index metadata, repair and resumable re-embedding support.
- Safer hook save failure reporting, index repair and provenance consistency.
- Documentation for WAL-safe backup and `N3MC_HOME` configuration.

For historical changes to earlier versions, see the repository's Git history.
