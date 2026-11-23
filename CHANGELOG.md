# Changelog

User-visible changes to N3MemoryCore Free for Codex.

## [1.9.1] - Unreleased

### Added
- CPU-only inference in the reference build.
- Structured role and source fields, explicit turn supersession and turn forgetting.
- Verified SQLite backup into a new folder, restore into a new home and full-metadata JSONL export.
- Record and turn identifiers in retrieved context, plus an output length limit.
- A GitHub Actions workflow that builds the package and publishes it to PyPI from a release tag.

### Changed
- Retired turns are excluded from normal search before result limits apply.
- The reference build defaults to no forced weak matches (`min_results=0`); existing explicit values are preserved.
- Vector search falls back to keyword search while embeddings use a different model or are being rebuilt.
- The instruction documents are v1.9.1 (`N3MemoryCore_v1.9.1_Free_EN.md`, `N3MemoryCore_v1.9.1_Free_JP.md`). They list the backup, restore, export, forget and supersede commands and the `min_results=0` default.
- README (EN/JP) rewritten: what is and is not saved, the block that reaches Codex, the names shared with the main N3MemoryCore Free edition, setup, and the commands above.

### Fixed
- Instruction documents: two sentences named another assistant instead of Codex.

### Removed
- The compatibility paths for another host: the `--hook-submit` and `--save-claude-turn` commands, the `n3mc_hook.py` and `n3mc_stop_hook.py` modules, the helpers that registered hooks in that host's settings file, and the rules-file template. The Codex hooks use `codex_entry.py` only, so nothing a Codex installation runs is removed. The instruction documents and the tests follow.

## [1.9.0] - 2026-11-18

- Codex `UserPromptSubmit` and `Stop` hooks capture prompts and final replies with the same turn ID.
- Hybrid vector and FTS retrieval, session-aware ranking and local SQLite storage.
- Index metadata, repair and resumable re-embedding support.
- Safer hook save failure reporting, index repair and provenance consistency.
- Documentation for WAL-safe backup and `N3MC_HOME` configuration.

For historical changes to earlier versions, see the repository's Git history.
