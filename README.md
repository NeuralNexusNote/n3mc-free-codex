# N3MemoryCore Free for Codex (n3mc-free-codex) v1.9.1

**Give Codex a memory across conversations. Free, on your own PC.**

Do you find yourself explaining an earlier decision and its reasons again in a new chat or another project?
N3MemoryCore saves your messages and Codex's replies on your PC and recalls them when related topics arise.
You do not need to say “remember this” each time. Two trusted hooks handle saving and retrieval.
N3MC supplies the **conversation-history layer**. Use it alongside standing instructions such as `AGENTS.md`.

The primary deliverable is the **implementation specification**. Your own Codex generates the code, sets it up and verifies it.

**For first-time users.** After building Free with the steps below, start a new chat in the same project and say “We chose blue for the prototype cover.” In another new chat, ask “Which color did we choose for the prototype cover?” Check the answer and the retrieved record. Keep the generated source and `tests/` for a later upgrade to Pro.

1. Create a dedicated empty folder in File Explorer.
2. Put `N3MemoryCore_v1.9.1_Free_EN.md` in that folder.
3. Open the folder as a local workspace in Codex.
4. Ask: “Implement this specification, complete setup, and run the verification tests.”
5. Review and trust both registered hooks in **Settings → Hooks** (CLI: `/hooks`). Codex performs the tests that follow.

Check Codex's **Evidence Report** for passing tests, including saving in a new chat and retrieval from another chat. See [Setup](#setup) for details.

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

```text
Your message → Search earlier memories → Save the current message
                        ↓
               Pass the results to Codex
                        ↓
                   Codex replies
                        ↓
               Stop hook saves the reply
```

Powered by Codex's hook system. Everything happens automatically — no user action required.

- **What is saved** — eligible messages and replies received by the hooks. Long messages are split into chunks; explicit opt-outs and inputs detected as containing secrets are excluded. A fenced code block is saved as `[code omitted]`: N3MC remembers what was said and decided, and the code is in your project's files.
- **What is recalled** — with every message, the hook searches the memory and adds the related records to Codex's context, before Codex reads your message.

### Three scenes

> **Monday** — You and Codex decide to use PostgreSQL for the website, and say why.
>
> **Wednesday** — In a new session you ask which database you chose. Monday's decision and its reason arrive in Codex's context together with your question. You do not explain it again.
>
> **Friday** — You are working in another folder. When the subject comes up, Monday's decision is recalled there too: Free keeps one memory for all your project folders.

### An example of what Codex receives

This illustrates the search-output format. Records saved by Claude Code on a connected server can also be retrieved; their agent labels and the stored reply label `[claude]` are retained.

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

### Standing instructions and conversation memory

| | Instructions such as `AGENTS.md` | N3MemoryCore |
|---|---|---|
| Main role | State working rules and recurring information | Retain earlier messages, replies and their reasons |
| Use | The user maintains the required instructions | Hooks save conversations and search them when related topics arise |
| Consideration | Make standing instructions explicit | Retrieval depends on search; recall is not guaranteed |

Keep recurring rules in instruction files and use N3MC for conversation history and the reasons behind decisions.

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

**Two ways to install**: The primary route is to have Codex implement the specification, configure it and verify it. The reference code is an alternative. In either case, the user reviews and trusts the registered hooks.

## Free or Lite? Which one to use

Free and MCP Lite are the two free N3MemoryCore products. This README describes **Free for Codex**.

| | Free for Codex | [N3MC MCP Lite](https://github.com/NeuralNexusNote/n3mcmcp-lite) |
|---|---|---|
| Use | Save and search through Codex hooks | Call memory tools from MCP clients; supported editions also have Claude Code hooks |
| Saving | Automatically saves eligible messages and replies | The AI decides what to save over MCP; hook-enabled editions save conversations automatically |
| Retention | No expiry | Automatically deleted after 7 days |
| Requirements | Python 3.10+ | Python 3.10+ and Docker (Redis Stack) |
| Setup | Generate and configure from the Codex specification | Use the Lite specification and configuration for your application |

- **Free for Codex** — For long-term Codex conversation memory. Normal saving and search require neither an MCP connection nor Docker.
- **MCP Lite** — For MCP clients or short-lived working memory. Check the supported client and required software for that edition.

**Free for Codex is not intended for:**

- Use as an MCP tool from other applications.
- Automatic removal of old records or deletion of individual records; Free has no such commands.
- Automatic synchronization between PCs; Free for Codex has no synchronization feature.

## Features

| You want to… | N3MemoryCore… | How |
|---|---|---|
| Stop explaining the same thing again | saves every message and reply, and recalls the related ones on every turn | Codex hooks (`UserPromptSubmit`, `Stop`). No tool call, no manual step |
| Find things in your own words | finds a past conversation even when the exact words differ | Vector search with `intfloat/multilingual-e5-base` (Japanese, English, Chinese, Korean and ~100 other languages) plus keyword search |
| Pick up tomorrow where you left off | keeps the memory across sessions and across project folders | One database for every folder; the conversation you are in is ranked first |
| Keep your data at home | stores the memory in a file on your own PC, not in any cloud service | SQLite. Only the memories recalled for a turn are sent to Codex, together with your message ([details](#your-memory-stays-on-your-pc)) |
| Spend fewer tokens | does the search with local embeddings (zero Codex tokens) and injects only the related records | The recalled block is capped (`top_matches_max`, `min_results`) |
| Let several agents share one memory | keeps who wrote each record | `agent_name`, `local_id`. Ranking each agent's own memories first is a Pro feature |
| Share memory with an existing Free/Pro server | saves and searches through a verified server on the same PC | Configure its data root and port (see connection settings below) |

To use another embedding model, set it in `config.json` and run `n3mc-free-codex --reembed`; the model must produce 768-dimension vectors.

## Your Memory Stays on Your PC

An AI that remembers you is convenient, but it is natural to ask where those memories are kept. N3MemoryCore keeps them in one place you control: a folder on your own PC.

- **One local file** — Standalone memory is stored in a single SQLite file, `~/.n3mc-free-codex/.memory/n3memory.db`. There is no N3MC account and no N3MC cloud service. To move it, set `N3MC_FREE_CODEX_HOME` (see [Optional: change where data lives](#optional-change-where-data-lives)).
- **The raw input is kept next to it** — `~/.n3mc-free-codex/.memory/audit.log` holds the raw text of nonexcluded hook calls (your messages and Codex's replies, code blocks included). It is rotated at 50 MB, and `n3mc-free-codex --list` does not show it. Treat it as private data, like the database.
- **Search runs on your PC** — The embedding model and the search run locally. N3MC's server listens only on `127.0.0.1` and rejects requests for any other host name, so other machines on your network cannot reach it.
- **No telemetry** — N3MC sends no usage data anywhere. The code is open, so you can check this yourself.
- **You can see and remove everything** — `n3mc-free-codex --list` shows what is stored. Deleting `~/.n3mc-free-codex/` removes all of it (see [Uninstall](#uninstall)). Backing up is copying two files (see [Backup and restore](#backup-and-restore)).

What does go over the network:

- **The embedding model download** — On the first search, `intfloat/multilingual-e5-base` (about 1.1 GB) is downloaded from Hugging Face. After that, the Hugging Face library may still check for model updates when the model loads; set `HF_HUB_OFFLINE=1` to stop this once the model is downloaded.
- **What Codex reads** — The memories recalled for a turn are added to that turn's prompt, so they are sent to OpenAI together with your message, as everything you type into Codex is. N3MC does not upload your memory database anywhere, but the parts Codex uses in a turn are part of that conversation.

In connected mode, memories are stored on the target server. The Codex-side audit remains local.

## Free vs Pro

| | Free | Pro |
|---|---|---|
| Core features (save, search, automatic recall) | ✅ | ✅ |
| Exact duplicates within the same turn skipped; the newest version of the same content listed first | ✅ | ✅ |
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

For Pro, choose the specification for your host. Check the destination and import-ID behavior when moving records. Connecting to an existing Free/Pro server is another option.

## Specification Files

| File | Description |
|---|---|
| `N3MemoryCore_v1.9.1_Free_JP.md` | Free edition (Japanese) |
| `N3MemoryCore_v1.9.1_Free_EN.md` | Free edition (English) |

> 💡 **A note on annotations in the specification**
> Throughout the specification file (Markdown), you'll find annotations describing the design intent behind each instruction — written to give you precise control over AI behavior. Before having Codex generate the code, take a moment to read through them. They contain more than just code: the logic behind how to work with AI effectively.

## Setup

**Method A, generating from the specification, is the primary route.** Method B is for those who want to use the reference code directly.

### Method A: Generate from the specification (primary, recommended)

1. **Create a dedicated folder** — Start with an empty folder, for example `C:/Users/<you>/n3mc-free-codex`. The generated code stays in use there.
2. **Add the specification** — Put `N3MemoryCore_v1.9.1_Free_EN.md` in the folder. Do not mix it with another project.
3. **Open it in Codex** — Use that folder as a local workspace.
4. **Ask for implementation** — Send:

```text
Implement N3MemoryCore Free for Codex according to N3MemoryCore_v1.9.1_Free_EN.md. Complete prerequisite checks, installation, hook registration, and the tests in sections 6 and 7. After registration, show me the two hooks to review and trust. Once trusted, perform the test inputs and verification commands yourself and report the results in the Evidence Report.
```

Codex checks the destination, Python and dependencies, then generates the code, installs it and registers the hooks. An already authorized destination does not need another confirmation. It must not overwrite another project.

5. **Trust both hooks** — In **Settings → Hooks** (CLI: `/hooks`), review and trust both `UserPromptSubmit` and `Stop` labeled `N3MC-Free-Codex memory`.
6. **Read the results** — Codex runs tests in new chats. Check the three-turn capture, cross-chat retrieval and opt-out tests in §6.1–§6.2, and the §7 test results.

**Generating code or registering hooks alone does not complete setup. Check the Evidence Report for passing required tests.** Any unverified item still needs verification.

The first model download may take several minutes. Moving or deleting an editable installation's source folder later breaks its hooks.

### Method B: Install the reference code (optional)

#### 1. Install

```bash
git clone https://github.com/NeuralNexusNote/n3mc-free-codex.git
cd n3mc-free-codex
python -m pip install -e ".[test]"
```

Python 3.10+ is required. The embedding model is downloaded on first use.

#### 2. Connect to Codex

```bash
n3mc-free-codex --init
```

- Creates `~/.n3mc-free-codex` and `config.json`, with `owner_id` and `local_id`. It initializes the DB in standalone mode.
- Registers `UserPromptSubmit` and `Stop` in the user's `~/.codex/hooks.json`; when `CODEX_HOME` is set, it uses that folder's `hooks.json`.
- Uses the installed Python's absolute path, a 120-second timeout and the `N3MC-Free-Codex memory` label.
- Preserves other handlers and backs up settings before changes. Invalid JSON is left untouched; repeated execution does not duplicate this edition's handlers.

The command does not grant hook trust. Codex uses the user's approval and sandbox settings.

#### 3. Verify hook registration

Have Codex check the configuration path, Python interpreter, one handler per event, and the 120-second timeout. For a manual Method B check, this command should print `OK`:

```bash
python -c "import os,json,base64,re; from pathlib import Path; p=Path(os.environ.get('N3MC_CODEX_HOOKS_PATH') or str(Path(os.environ.get('CODEX_HOME') or str(Path.home()/'.codex'))/'hooks.json')).expanduser(); h=json.loads(p.read_text(encoding='utf-8-sig')).get('hooks',{}); norm=lambda c: base64.b64decode(c.rsplit(' ',1)[-1]).decode('utf-16le') if '-EncodedCommand ' in c else c; groups=[[x for g in h.get(e,[]) for x in g.get('hooks',[]) if x.get('type')=='command' and re.search(r'(?<![A-Za-z0-9_.-])n3memorycore_free_codex[.]codex_entry(?![A-Za-z0-9_.-])',norm(x.get('command',''))) and re.search(r'(?<![A-Za-z0-9_-])'+f+r'(?![A-Za-z0-9_-])',norm(x.get('command','')))] for e,f in [('UserPromptSubmit','--prompt'),('Stop','--stop')]]; assert all(len(g)==1 and g[0].get('timeout')==120 for g in groups), 'Free Codex hook registration missing, duplicated or invalid'; print('OK')"
```

`OK` checks registration structure. It does not prove trust or that a conversation was saved. If registration is missing, rerun `n3mc-free-codex --init` with the same Python.

#### 4. Review and trust the hooks

In **Settings → Hooks** (CLI: `/hooks`), review and trust `UserPromptSubmit` and `Stop` labeled `N3MC-Free-Codex memory`. Then start a new chat in a workspace outside the installation folder.

#### 5. Confirm it works

Have Codex execute §6.1–§6.2 of the specification. All three turns must contain an input (`[user]`) and reply (`[claude]`), with matching `turn_id` values within each pair and different IDs across turns. `agent_name` is `codex`; all pairs from the same chat share one `session_id`. Do not substitute manual `--buffer` calls for automatic capture.

```bash
n3mc-free-codex --list --format jsonl
```

Also verify retrieval in another chat whose questions omit the answers, exclusion of both opted-out input and reply, and the §7 test results. In connected mode, inspect the target DB.

#### Optional: change where data lives

Set `N3MC_FREE_CODEX_HOME` to an absolute path before `--init`, in an environment visible to both Codex and the verification terminal. A terminal-only setting does not reach a separately launched Codex. Reopen Codex and the terminal after changing the variable so they inherit it.

### Troubleshooting

**`n3mc-free-codex: command not found`**
The installed Python's `Scripts/` (Windows) or `bin/` (Linux) may not be on PATH. Use `python -m n3memorycore_free_codex.n3memory --init` with the same interpreter, and check that you have not switched Python environments.

**Registered hooks, but no records**
Have Codex inspect trust, execution errors, the registered interpreter and the data root. In connected mode, the Codex edition's `--list` does not read the target; inspect the target DB. Ordinary turns leave entries in `.memory/audit.log`; opt-out and secret exclusions suppress the audit too.

**The prompt is saved but the reply is missing**
Inspect `Stop`. If both are saved but another chat cannot retrieve them, inspect that chat's `UserPromptSubmit` output.

**The first search is unavailable**
Model download or loading may take time. Inspect the error and `.memory/server.log` under the data root. An unavailable search is not evidence of successful saving or completed verification.

### What to expect after setup

- Related earlier conversations are searched and passed to Codex.
- Hooks save messages and replies; repeated manual saving is unnecessary.
- Codex briefly acknowledges recalled information when it actually uses it.
- Failed saves are reported. Successful automatic saves do not produce an acknowledgment each time.

### Search settings

Standalone settings are in `~/.n3mc-free-codex/config.json`; see the specification for their names and meanings. Connected mode uses the target's search settings.

### Backup and restore

Keep `.memory/n3memory.db` (memory data) and `config.json` (including `owner_id` and `local_id`) together. Use SQLite's backup facility for a running DB, or stop the relevant standalone server before making a consistent copy. Restore both files to the same data root.

Keep `audit.log` and `audit.log.1` too if you need raw text. In connected mode, back up the target DB and settings as well as the Codex-side audit.

### Uninstall

You can ask Codex: “Remove N3MemoryCore Free for Codex, but keep my memory data.” To do it yourself:

1. Remove only this edition's `UserPromptSubmit` and `Stop` registrations from Codex settings. Preserve other products' hooks.
2. If this edition's standalone server is running, identify it by command and data root and stop only that server. Do not stop a connected Free/Pro target.
3. Uninstall with the Python used for installation.

```bash
python -m pip uninstall n3memorycore-free-codex
```

4. Keep the data folder for restoration. Delete it only if you also want to erase the memory and have checked your backup; deleted data cannot be recovered.

### Connect to an original Free or Pro server

If an original Free/Pro server already runs on the same PC, Codex can save and search conversations there. Set its port and absolute data-folder path in the Codex edition's `config.json`.

```json
{
  "connect_server_port": 18521,
  "connect_server_root": "C:/Users/<you>/.n3mc-pro"
}
```

This is a Pro example. Set both values for the actual target and start it beforehand. Clear both to return to standalone mode.

- Save and search on the target only after verifying it. The client does not start, stop or repair the target.
- Codex keeps a local audit but does not duplicate connected records in a local DB. An unavailable target does not trigger a fallback to another DB.
- The Codex edition's `--list`, `--show-turn` and `--recall-thread` read local data. Read connected full text with the target product's CLI and data root (specification §3).
- `--list --format jsonl` exports all IDs from standalone records. Which IDs survive import depends on the receiver; verify this with disposable data before migration.

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

- A local **Codex** client supporting command hooks.
- **Python 3.10+**. Codex follows the specification to guide you if prerequisites are missing.
- **Target OS**: Windows 11 and Ubuntu. macOS is not supported.

## Extensibility

Discuss extensions with Codex. The following are examples of additions made by changing the specification; distinguish them from the standard Free Codex features.

- **MCP server** — Expose N3MC as an MCP server so other AI tools can access the memory
- **PostgreSQL migration** — Move from SQLite to PostgreSQL + pgvector (a ready-made edition for a team in one organization is N3MC Pro on PostgreSQL, `n3mc-pro-postgres`)
- **Custom search logic** — Tune bias coefficients and ranking formulas
- **Alternative embedding models** — Swap in a different model to suit your use case
- **Keyword-search tokenizer** — The default keyword index (FTS5 `trigram`, plus a 2-character index for Japanese, Chinese and Korean) was chosen because it works both for languages written without spaces and for languages like English . Adapt the final tokenizer to your own language and environment (e.g. `porter unicode61` to fold English word forms, or a morphological analyzer for higher Japanese precision). Codex can do it for you, including the start-up check that otherwise rebuilds the index as `trigram`, and rebuilding the existing DB's FTS index
- **Custom ID fields** — Add fields like `project_id` or `tag` to organize memories your way
- **PDF import** — Extract text from PDF files and store them as searchable memories
- **Hashtag support** — Codex auto-tags memories with `#hashtags` for filtered search (e.g. `--search "#AWS"`) — works with existing FTS, no DB changes needed

Load the specification into Codex, discuss the addition, and have it update the specification, generate the code and run verification tests.

---

Apache License 2.0 — Copyright (C) 2026 NeuralNexusNote™ / ArnolfJp019
See [LICENSE](./LICENSE) for details.
