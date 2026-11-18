# Changelog

User-visible changes to N3MemoryCore Free for Codex.

## [Unreleased]

### Added
- CPU-only inference in the reference build.
- Structured role and source fields, explicit turn supersession and turn forgetting.
- Verified SQLite backup into a new folder, restore into a new home and full-metadata JSONL export.
- Record and turn identifiers in retrieved context, plus an output length limit.

### Changed
- Retired turns are excluded from normal search before result limits apply.
- The reference build defaults to no forced weak matches (`min_results=0`); existing explicit values are preserved.
- Vector search falls back to keyword search while embeddings use a different model or are being rebuilt.
- The v1.9.0 instruction documents continue to describe the instruction-based build; the additional reference-code commands are outside that specification.

## [1.9.0] - 2026-11-18

- Codex `UserPromptSubmit` and `Stop` hooks capture prompts and final replies with the same turn ID.
- Hybrid vector and FTS retrieval, session-aware ranking and local SQLite storage.
- Index metadata, repair and resumable re-embedding support.
- Safer hook save failure reporting, index repair and provenance consistency.
- Documentation for WAL-safe backup and `N3MC_HOME` configuration.

For historical changes to earlier versions, see the repository's Git history.
