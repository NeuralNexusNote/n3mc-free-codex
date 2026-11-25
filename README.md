# N3MemoryCore Free for Codex v1.9.1

N3MemoryCore keeps a searchable conversation history for Codex on your PC. Once you trust both hooks, they recall related records before a prompt is saved and save the final reply when the turn ends. The memory carries across chats and projects using SQLite and local embeddings.

[日本語](README_JP.md) · [English implementation specification](N3MemoryCore_v1.9.1_Free_EN.md)

> **⚠️ Disclaimer**
>
> - **No support, no claims**: This project is provided as-is with no support. Questions, bug reports, and feature requests are not guaranteed a response. Use entirely at your own discretion.
> - **Use at your own risk**: This system runs on AI-generated code. The author is not responsible for any data changes or issues caused by its use.
> - **Backup first**: Always back up your current environment before running this on important projects.

> **⚠️ How long memories are kept, and data size**
>
> - **Memories are not deleted.** Free has no feature that deletes old records.
> - **More data makes it slower.** The more records there are, the longer a search takes.

> A NeuralNexusNote™ product
>
> 🇯🇵 **[Click here for the Japanese Documentation (日本語版)](./README_JP.md)**
> 🛡️ **[Development Philosophy & AI-Native Policy](./PHILOSOPHY.md)**

## How It Works

```
User's message
    │
    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  1. Auto-save │────▶│ 2. Semantic   │────▶│ 3. Context    │
│  Save last    │     │    search     │     │    injection   │
│  response     │     │  Find related │     │  Feed to       │
│  to DB        │     │  memories     │     │  Codex        │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
                                                 ▼
                                          Codex responds
                                          with full context
```

Powered by Codex's hook system. Everything happens automatically — no user action required.

- **What is saved** — every message you send and every reply of Codex, as written. A fenced code block is saved as `[code omitted]`: N3MC remembers what was said and decided, and the code is in your project's files. Input that Codex itself injects (task notifications, agent messages, system reminders) is not saved.
- **What is recalled** — with every message, the hook searches the memory and adds the related records to Codex's context, before Codex reads your message.

### Three scenes

> **Monday** — You and Codex decide to use PostgreSQL for the website, and say why.
>
> **Wednesday** — In a new session you ask which database you chose. Monday's decision and its reason arrive in Codex's context together with your question. You do not explain it again.
>
> **Friday** — You are working in another folder. When the subject comes up, Monday's decision is recalled there too: Free keeps one memory for all your project folders.

### What Codex receives

This is the block the hook added for the Wednesday question. It was captured from a real run of the hooks (a temporary data folder; the second session was started in a different folder from the first).

```text
# Recalled Memory Context
Search query: Which database did we decide to use for the website, and why?

## Top matches (use these to answer the question)

_If several versions of the same content appear, the one with the newest `saved` time is the current one._

## [1] score=0.5283 saved=2026-11-22 15:58 (UTC+0900) claude-code
[user] Let's use PostgreSQL for the website's database. Several people will edit at the same time, and SQLite locks the whole file on every write.

## Possibly related (weak matches — may be unrelated)

## [2] score=0.3339 saved=2026-11-22 15:58 (UTC+0900) claude-code
[claude] Agreed, PostgreSQL it is. The reason, for the record: several editors at the same time, and SQLite allows one writer at a time. Next step: write the schema for the articles table.

## Previous matching Q-A exchanges (supplementary context)

### turn_id: 9df50a6f-8a92-4401-b096-9e3daec22566 saved=2026-11-22 15:58 (UTC+0900)
[user] Let's use PostgreSQL for the website's database. Several people will edit at the same time, and SQLite locks the whole file on every write.
[claude] Agreed, PostgreSQL it is. The reason, for the record: several editors at the same time, and SQLite allows one writer at a time. Next step: write the schema for the articles table.
```

`Top matches` are the records that passed the relevance floors. `Possibly related` are the closest of the records that did not. The last part shows the whole exchange a top match belongs to.

## About this project

🛡️ AI-Native Development Policy
This project prioritizes Instructions over Static Code. Please read our [Development Philosophy](./PHILOSOPHY.md) to understand why you should let AI generate your execution environment.

> I know Java and C#, but Python is completely new to me.
> The code Claude Code generated — I built it without fully understanding it.
>
> But I tested it, refined the specification, rebuilt it,
> and shipped both Japanese and English versions — Free and Pro.
>
> Because if I could do it, so can you.
>
> The first draft of the specification was written by Copilot.
> Claude Code turned it into working code. Gemini reviewed it.
> Iterated across three AIs — that process is N3MemoryCore.

**Two ways to install**: generate from the specification in Codex or install the package from the repository. Review and trust both registered hooks before relying on capture. (See [Setup](#setup) below.)

## Features

| You want to… | N3MemoryCore… | How |
|---|---|---|
| Stop explaining the same thing again | saves eligible messages and replies, and recalls the related ones on every turn | Codex hooks (`UserPromptSubmit`, `Stop`). No tool call, no manual step |
| Find things in your own words | finds a past conversation even when the exact words differ | Vector search with `intfloat/multilingual-e5-base` (Japanese, English, Chinese, Korean and ~100 other languages) plus keyword search |
| Pick up tomorrow where you left off | keeps the memory across sessions and across project folders | One database for every folder; the conversation you are in is ranked first |
| Keep your data at home | stores the memory in a file on your own PC, not in any cloud service | SQLite. Only the memories recalled for a turn are sent to Codex, together with your message ([details](#your-memory-stays-on-your-pc)) |
| Spend fewer tokens | does the search with local embeddings (zero Codex tokens) and injects only the related records | The recalled block is capped (`search_result_limit`, `min_results`) |
| Let several agents share one memory | keeps who wrote each record | `agent_name`, `local_id`. Ranking each agent's own memories first is a Pro feature |

To use another embedding model, set it in `config.json` and run `n3mc-free-codex --reembed`; the model must produce 768-dimension vectors.

## Your Memory Stays on Your PC

An AI that remembers you is convenient, but it is natural to ask where those memories are kept. N3MemoryCore keeps them in one place you control: a folder on your own PC.

- **One local file** — Every memory is stored in a single SQLite file, `~/.n3mc-free-codex/.memory/n3memory.db`. There is no N3MC account and no N3MC cloud service. To move it, set `N3MC_FREE_CODEX_HOME` .
- **The raw input is kept next to it** — `~/.n3mc-free-codex/.memory/audit.log` holds the raw text of eligible hook calls (your messages and Codex's replies, code blocks included). It is rotated at 50 MB, and `n3mc-free-codex --list` does not show it. Treat it as private data, like the database.
- **Search runs on your PC** — The embedding model and the search run locally. N3MC's server listens only on `127.0.0.1` and rejects requests for any other host name, so other machines on your network cannot reach it.
- **No telemetry** — N3MC sends no usage data anywhere. The code is open, so you can check this yourself.


What does go over the network:

- **The embedding model download** — On the first search, `intfloat/multilingual-e5-base` (about 1.1 GB) is downloaded from Hugging Face. After that, the Hugging Face library may still check for model updates when the model loads; set `HF_HUB_OFFLINE=1` to stop this once the model is downloaded.
- **What Codex reads** — The memories recalled for a turn are added to that turn's prompt, so they are sent to OpenAI together with your message, as everything you type into Codex is. N3MC does not upload your memory database anywhere, but the parts Codex uses in a turn are part of that conversation.

## Free vs Pro

| | Free | Pro |
|---|---|---|
| Core features (save, search, automatic recall) | ✅ | ✅ |
| Exact duplicates skipped; the newest version of the same content listed first | ✅ | ✅ |
| The conversation you are in ranked first (`b_session`) | ✅ | ✅ |
| The current project's memories recalled first | - | ✅ |
| Search that stays fast as the memory grows | - | ✅ Above 20,000 records an in-memory index narrows the candidates |
| The previous session's thread at session start | - | ✅ |
| Your own agent's / install's memories ranked first (`b_local`) | - | ✅ |
| Delete individual records | - | ✅ |
| Retention period (`--gc`) | - | ✅ Off by default; you run it yourself |
| Export / import | - | ✅ Data migration & sharing |
| Entity index | - | ✅ |

Nothing is deleted or replaced automatically in either edition.

**Start with Free.** You can upgrade to Pro later using the Upgrade specification.

## Specification Files

| File | Description |
|---|---|
| `N3MemoryCore_v1.9.1_Free_JP.md` | Free edition (Japanese) |
| `N3MemoryCore_v1.9.1_Free_EN.md` | Free edition (English) |

> 💡 **A note on annotations in the specification**
> Throughout the specification file (Markdown), you'll find annotations describing the design intent behind each instruction — written to give you precise control over AI behavior. Before having Codex generate the code, take a moment to read through them. They contain more than just code: the logic behind how to work with AI effectively.

## Setup

### Generate in Codex

1. Install Python 3.10 or newer and use a Codex client with command hooks. Open a dedicated empty folder or the existing Free Codex checkout in Codex. The editable installation continues to use that folder.
2. Place this specification in the folder. Ask Codex: “Implement N3MemoryCore Free for Codex according to this specification. Generate the code in this folder and run the isolated tests.”
3. Codex checks the destination, generates the files, and runs §6–§7 against disposable data. For an existing checkout, preserve unrelated files and recoverable local changes. Do not register the user's hooks as part of code-only regeneration.
4. To enable memory, install and register from the dedicated folder:

```bash
python -m pip install -e ".[test]"
n3mc-free-codex --init
```

5. In Codex **Settings → Hooks** (CLI: `/hooks`), inspect and trust both Free Codex hooks. Start a new chat and verify automatic save and cross-chat recall (§6). The first semantic search may need to download the multilingual embedding model.

### Install from source

Clone the Free Codex repository and run step 4 in the checkout. A regular `python -m pip install .` also works. Review and trust both hooks as in step 5.

### Data and backup

Back up the local `config.json` and a consistent copy of `.memory/n3memory.db` together from `~/.n3mc-free-codex`. Set `N3MC_FREE_CODEX_HOME` to use another folder. For uninstall, remove only this edition's two hook handlers from the Codex settings first, then uninstall the distribution. Keep the data backup if you want to restore it later.

### Optional connection to an original Free or Pro server

Standalone is the default. Set both `connect_server_port` (a loopback port) and `connect_server_root` (the server's absolute data-folder path) in `config.json` to use connected mode. Defaults are `null`. With either unset, continue in standalone mode; if only one is set, emit the `connection_incomplete` notice and clear it when both are set or both are unset. Before each search or save, validate `GET /health`: its absolute `root` must match the configured root after `os.path.normcase(os.path.abspath(...))`. The target's `code_version` may differ.

Send searches to `POST /search` and eligible prompt/reply chunks to `POST /buffer` on the verified target. Save `agent_name: codex`, the hook's `session_id` and `turn_id`, and the Codex installation's `local_id`; omit `owner_id` so the target assigns its own owner. For hooks with a nonblank string `cwd`, send `project` as the Git root folder name, falling back to the working folder name; omit it if `cwd` is absent. Pro stores `project`; Free ignores it. Keep the local audit events, but never save connected records to the local DB. A failed health check or write must not fall back to local storage. Report prompt write failures with `systemMessage` while retaining recalled context; report Stop write failures with a nonzero status. A failed search returns “memory search unavailable” and does not prevent a separately verified save.

The connected client never starts, stops, restarts, repairs, or re-embeds the target. `--buffer` uses the same verified remote save path; `--repair` and `--reembed` require standalone mode. Listing, full-turn display and thread reconstruction read the local DB only. To read connected full text, use the target product's CLI with its data-root environment variable and `--show-turn <turn_id>` or `--recall-thread <turn_id>` (Free: `python -m n3memorycore.n3memory`, `N3MC_HOME`; Pro: `python -m n3memorycore_pro.n3memory`, `N3MC_PRO_HOME`). Never migrate data automatically.

For standalone records, `--list --format jsonl` exports every identity field for later import: `id`, `timestamp`, `agent_name`, `content`, `session_id`, `turn_id`, `owner_id`, `local_id`. JSONL stdout contains only objects; its total goes to stderr. Import behavior belongs to the receiving product: verify which IDs it preserves before migrating real data. The current local Pro importer preserves `turn_id` but does not preserve `session_id`; this export alone cannot guarantee full conversation reconstruction after import.

## ID Hierarchy

N3MemoryCore uses 6 ID fields to identify the origin and context of each record:

| ID | Stored in | Generated | Granularity | Purpose |
|---|---|---|---|---|
| `id` (PK) | DB record | Per record (UUIDv7, time-ordered) | **One record** | Unique identifier for each memory |
| `owner_id` | `config.json` | First startup (UUIDv4) | **Owner / data folder** | Identifies whose data this is — for shared/multi-user scenarios and import provenance |
| `local_id` | `config.json` / API | First startup (UUIDv4), or per request | **Install** | One Codex install has one `local_id`; it is the same in every session. Stored on every record (in Free it is not used in ranking; `b_local` is a Pro feature) |
| `session_id` | Supplied by Codex (hook input), else made per process | Per conversation | **One conversation** | Groups the memories of one conversation. In Free, drives the `b_session` ranking bias (match=1.0, mismatch=0.6) so the ongoing exchange ranks above unrelated past sessions |
| `turn_id` | DB record | Supplied by the Codex hook event | **One exchange** | Ties one user message to the reply that answers it; `--show-turn` and `--recall-thread` take it |
| `agent_name` | DB record | Per save (free-form string) | **Display label** | Human-readable label of the writer (`"codex"` for the hooks). `--buffer --agent-id <name>` sets this field |

```
owner_id  (the data folder ~/.n3mc-free-codex and its owner)
  └── local_id  (the install; the same in every session)
        └── session_id  (one Codex conversation)
              └── turn_id  (one exchange: one user message and the reply to it)
                    └── id  (one record = one chunk)

agent_name  (a display label, outside the hierarchy: "codex" for the hooks)
```

## Requirements

- **Codex** (required)
- **Python 3.10+**
- **OS**: Windows 11 and Ubuntu (tested). macOS is not supported.

> To check if Python is installed, run `python --version` in your terminal.
> If missing, Codex will guide you during setup.

## Extensibility

N3MemoryCore is built from a specification, so extending it is as simple as asking Codex.

- **MCP server** — Expose N3MC as an MCP server so other AI tools can access the memory
- **PostgreSQL migration** — Move from SQLite to PostgreSQL + pgvector (a ready-made edition for one person on one PC is N3MC Pro on PostgreSQL, `n3mc-pro-postgres`)
- **Custom search logic** — Tune bias coefficients and ranking formulas
- **Alternative embedding models** — Swap in a different model to suit your use case
- **Keyword-search tokenizer** — The default keyword index (FTS5 `trigram`, plus a 2-character index for Japanese, Chinese and Korean) was chosen because it works both for languages written without spaces and for languages like English (the PyPI package is used in every country). Adapt the final tokenizer to your own language and environment (e.g. `porter unicode61` to fold English word forms, or a morphological analyzer for higher Japanese precision). Codex can do it for you, including the start-up check that otherwise rebuilds the index as `trigram`, and rebuilding the existing DB's FTS index
- **Custom ID fields** — Add fields like `project_id` or `tag` to organize memories your way
- **PDF import** — Extract text from PDF files and store them as searchable memories
- **Hashtag support** — Codex auto-tags memories with `#hashtags` for filtered search (e.g. `--search "#AWS"`) — works with existing FTS, no DB changes needed

Just load the specification into Codex and say what you want to add.

---

Apache License 2.0 — Copyright (C) 2026 NeuralNexusNote™ / ArnolfJp019
See [LICENSE](./LICENSE) for details.
