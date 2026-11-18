# N3MemoryCore (N3MC) — Free for Codex

> **⚠️ How long memories are kept, and data size**
>
> - **No automatic expiry.** Records remain until you explicitly remove them. Keep backups of important memories.
> - **Data grows over time.** Search time and disk usage depend on the volume of records and the environment.

> A NeuralNexusNote™ product

🛡️ AI-Native Development Policy
This project prioritizes Instructions over Static Code. Please read our Development Philosophy to understand why you should let AI generate your execution environment.

> 🇯🇵 **[Click here for the Japanese Documentation (日本語版)](./README_JP.md)**
> 🛡️ **[Development Philosophy & AI-Native Policy](./PHILOSOPHY.md)**

This is the Codex adaptation of [N3MemoryCore Free for Claude Code](https://github.com/NeuralNexusNote/n3mc-free). This repository brings its instruction-led setup to Codex.

**The primary workflow is to give Codex the instruction document and let it build N3MemoryCore for your environment.** A reference implementation is also provided for inspection and direct installation. Both paths are described below; MCP is not required.

## Choose your edition

| Edition | Integration | Where to start |
|---|---|---|
| **Free for Codex (this repository)** | Codex UserPromptSubmit / Stop hooks | [Instruction documents](#specification-files), then Path A |
| [Free for Claude Code](https://github.com/NeuralNexusNote/n3mc-free) | Claude Code hooks | The Claude Code repository's instructions |
| [MCP Lite](https://github.com/NeuralNexusNote/n3mcmcp-lite) | MCP | Its own requirements and installation guide |

Use the instructions for your host application. Hook configuration and acceptance results are not interchangeable between editions.

## Features

- 💾 **Stored locally** — Your memories are kept in a file on your own PC, not in any cloud service. Only the memories recalled for a turn are sent to Codex, together with your message ([details](#your-memory-stays-on-your-pc)).
- 🔍 **Semantic search** — Finds relevant past conversations even when the exact words differ. Multilingual by default (`intfloat/multilingual-e5-base`) — supports multilingual retrieval, with accuracy depending on the question and stored content. Changing models requires checking dimensions and rebuilding embeddings; changing the configuration alone is not sufficient.
- 🔄 **Persistent across sessions** — Pick up tomorrow where you left off today.
- ⚡ **Works automatically** — After hook registration, trust and acceptance checks, prompts and final replies are captured and relevant history is retrieved automatically. Do-not-save requests and detected credentials are excluded; fenced code is replaced with `[code omitted]`, and images are not archived.
- 🤖 **Multi-agent ready** — Multiple AI agents can share one memory DB; every record keeps the agent that wrote it (`agent_name`, `local_id`). These fields describe provenance, not authentication or access control.
- 🔗 **Portable local data** — Back up the SQLite database together with its configuration. Check schema and embedding-model compatibility before migrating between implementations; automatic cross-edition merging is not promised.
- 💬 **Less repeated explanation** — Retrieved history can help you resume earlier work. Embedding inference runs locally, but injected memories consume Codex input context; lower total token cost is not guaranteed.

## How It Works

```text
User prompt
    → UserPromptSubmit: search earlier records and save the user message
    → Relevant history is passed to Codex
    → Codex responds
    → Stop: save the final reply with the same turn_id
```

Automatic capture depends on both hooks being trusted and enabled in the Codex environment you use. Retrieved history can be incomplete or irrelevant; verify evidence before treating it as a current fact.

### AGENTS.md and searchable memory

Use `AGENTS.md` for instructions that should always apply. N3MemoryCore searches prior exchanges and passes relevant history through hook stdout. Recalled context is historical data, not a new instruction.

## Your Memory Stays on Your PC

An AI that remembers you is convenient, but it is natural to ask where those memories are kept. N3MemoryCore keeps them in one place you control: a file on your own PC.

- **One local file** — Every memory is stored in a single SQLite file, `~/.n3mc/.memory/n3memory.db`. There is no N3MC account and no N3MC cloud service. To move it, set `N3MC_HOME` (see [Optional: change where data lives](#optional-change-where-data-lives)).
- **Search runs on your PC** — The embedding model and the search run locally. N3MC's server listens only on `127.0.0.1` and rejects requests for any other host name, so other machines on your network cannot reach it.
- **No telemetry** — N3MC sends no usage data anywhere. The code is open, so you can check this yourself.
- **You can see and remove everything** — `n3mc --list` shows what is stored. See [Uninstall](#uninstall) for removal and [Backup and restore](#backup-and-restore) for a consistent backup, including recent writes.

What does go over the network:

- **The embedding model download** — On the first model load, `intfloat/multilingual-e5-base` is downloaded from Hugging Face. After that, the Hugging Face library may still check for model updates when the model loads; set `HF_HUB_OFFLINE=1` to stop this once the model is downloaded.
- **What Codex reads** — Recalled memories are added to the turn's prompt and sent to the service processing the Codex conversation. N3MC does not upload the entire memory database, but the recalled parts become part of that conversation.

## Instruction documents and reference implementation

The v1.9.0 instruction documents define the instruction-based build. The reference code also contains later CPU, lifecycle and recovery improvements. These improvements have **not** been added to those instruction documents. Regenerating from the instructions therefore does not reproduce every feature of the current reference code.

| Capability | v1.9.0 instructions | Current reference code |
|---|---|---|
| Local storage, hybrid search, Codex hooks | Included | Included |
| Explicit turn supersession and forgetting | Not specified | Available |
| Backup / restore CLI and full-metadata export | Not specified; SQLite backup procedure provided | Available |
| Default weak-result filling (`min_results`) | 3 | 0; existing explicit settings are retained |

The reference build exposes these additional commands through `python -m n3memorycore.n3memory --help`. The historical Free/Pro comparison from the Claude Code edition is not a compatibility guarantee for this Codex adaptation.

## Specification Files

| File | Description |
|---|---|
| [N3MemoryCore_v1.9.0_Free_JP.md](N3MemoryCore_v1.9.0_Free_JP.md) | Codex Free instructions (Japanese) |
| [N3MemoryCore_v1.9.0_Free_EN.md](N3MemoryCore_v1.9.0_Free_EN.md) | Codex Free instructions (English) |

> 💡 **A note on annotations in the specification**
> Throughout the specification file (Markdown), you'll find annotations describing the design intent behind each instruction — written to give you precise control over AI behavior. Before having Codex generate the code, take a moment to read through them. They contain more than just code: the logic behind how to work with AI effectively.

## Setup

There are two supported setup paths. Pick whichever fits your style.

### Path A — AI-Native Setup (canonical)

1. Prepare a dedicated empty folder and open Codex there. Keep it after installation: the hooks may execute code from this folder.
2. Download one of the instruction documents above and give it to Codex.
3. Ask: "Implement N3MemoryCore according to this instruction document. Use CPU only. Confirm the installation folder, preserve existing settings, and report which checks passed and which still require my actions."
4. Let Codex generate and check the implementation. Restart Codex, inspect and trust the resulting hooks, then test a fresh chat over multiple turns.

The instructions use **Path A** for generation and **Path B** for direct installation. Implementation time depends on the environment, dependencies and model download. A generated implementation must pass its own acceptance checks; tests of the reference code do not establish that it works.

The user confirmed that Codex generated code from the instructions in a Hyper-V virtual machine and reported passing the appendix's three manual checks: data flow, CLI specification comparison, and saving with `--buffer` followed by `--search` in a separate session. Hook trust and automatic capture/recall in a fresh Codex chat are separate checks.

### Both paths: trust and enable the Codex hooks

Registration in `~/.codex/hooks.json` by `--init` or the generated implementation is separate from trusting and enabling the commands in Codex. Check them in this order:

1. Open `~/.codex/hooks.json`. Under `UserPromptSubmit` and `Stop`, inspect the Python path and the `n3memorycore.codex_entry --prompt` / `--stop` commands. For generated code, inspect the commands it actually produced.
2. Exit and restart Codex. During the Hyper-V installation, the new hooks could be approved after restarting.
3. Open `/hooks` in a Codex chat. Inspect, trust and enable **both** UserPromptSubmit and Stop. Both are needed to capture a prompt and its final reply as one turn.
4. Open a new chat, provide a short fictional passphrase, and check that the prompt and reply appear in `--list`. In another new chat, ask for the passphrase without repeating it.

Two entries in `hooks.json` and successful manual `--buffer` / `--search` commands do not establish that Codex ran the hooks.

### Path B — Install the reference code

This path uses the code in this repository. It does not test whether Codex can implement the instruction document.

#### 1. Install

Use a dedicated Python environment. The distribution currently shares the name `n3memorycore-free` with the original edition, so do not install both into the same environment. The PyPI command for the original edition is not the installation route for this Codex checkout.

Windows PowerShell:

```powershell
git clone https://github.com/NeuralNexusNote/n3mc-free-codex.git
cd n3mc-free-codex
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m n3memorycore.n3memory --init
```

In subsequent examples, `python` means that same environment's interpreter; on Windows use `.\.venv\Scripts\python.exe`. Do not delete or move the environment after hook registration.

Requirements: Python 3.10+ and a Codex environment that supports both hooks. The reference model uses CPU. Initial dependency/model downloads require a network connection, disk space and time; later searches can use the cached model.

#### 2. Connect to Codex

```bash
python -m n3memorycore.n3memory --init
```

This prepares `~/.n3mc/` and registers UserPromptSubmit and Stop commands in the user-global `~/.codex/hooks.json`. It preserves other hooks and backs up the file before changing it. Commands use the absolute Python interpreter path used for installation. Follow the shared steps above: restart Codex, then inspect, trust and enable both commands in `/hooks`.

#### 3. Verify the hook registration

Confirm that UserPromptSubmit and Stop each contain one `n3memorycore.codex_entry` command in `~/.codex/hooks.json`. Also confirm both are trusted and enabled in `/hooks`. JSON registration alone does not prove automatic capture.

#### 4. Open a new chat

After trusting and enabling the hooks, open a fresh Codex chat. Verify actual prompt and Stop execution rather than relying only on the presence of `hooks.json`.

#### 5. Confirm it's working

In a fresh Codex session, send any message. After Codex responds, run:

```bash
python -m n3memorycore.n3memory --list
```

You should see at least two records — one with a `[user]` prefix (your message) and one with a `[claude]` prefix (Codex's response). The legacy `[claude]` label is retained for compatibility; in this edition it stores Codex's reply. Then verify recall in another chat. If capture is missing, see **Troubleshooting** below.

#### Optional: change where data lives

Override the data location by setting `N3MC_HOME=/path/to/dir`. It is read at runtime, not persisted by `--init`. Set the same value in both the CLI environment and the environment that launches Codex hooks.

---

### Troubleshooting (both paths)

If capture is missing, inspect trust and enabled state for both hooks in Codex `/hooks`, then open a new chat. Hook failures appear on stderr. Check `~/.n3mc/.memory/server.log` and `audit.log`. If the model is not cached, check network access for the initial download.

### What to expect after setup

After the hook trust and multi-turn checks pass:
- Past conversations relevant to your current message are retrieved and injected automatically
- Codex can use retrieved excerpts when relevant; retrieval does not guarantee that every earlier detail will be available
- Saving and searching happen in the background — no action needed on your part

### Tuning recall (vector_min_cos)

N3MC finds records whose meaning is close to your question with vector search.
`vector_min_cos` is the threshold for "how close is close enough to be a
candidate" (default 0.85).

| If you | What happens |
|---|---|
| lower it (e.g. 0.80–0.83) | Records are found even when the wording differs, and short questions recall more. Less related records also come in, and the injected context gets longer |
| raise it (e.g. 0.88) | Fewer loosely related records and shorter injected context. Related records are also dropped more easily |

A sensible range is 0.80–0.88. Set it in `~/.n3mc/config.json`, e.g.
`"vector_min_cos": 0.83`. It takes effect from the next question (the server
restarts automatically). If the file has a typo and cannot be read, it is left
untouched and N3MC runs with defaults until you fix it; a notice about this
appears at the top of the recalled context once a day. Write numbers without
quotes.

### Weak matches (min_results)

The v1.9.0 instruction-based build specifies `min_results=3`: if fewer records pass the relevance filters, it can fill from dropped candidates under `## Possibly related (weak matches — may be unrelated)`. Filling is limited by the available candidates and does not guarantee a result.

The current reference code defaults to `min_results=0`, so it does not force weak results into the context. An existing `config.json` with an explicit value of 3 keeps that behavior. Set `"min_results": 0` to disable filling. Lower thresholds and more candidates can improve recall but also introduce unrelated material.

Age alone does not exclude a record from search. In the reference build, explicit supersession or forgetting does exclude a turn from normal retrieval.

### Backup and restore

SQLite uses WAL mode: copying only a live `n3memory.db` can miss recent writes. Use the SQLite backup API in the [backup procedure](docs/BACKUP.md) to create a consistent database snapshot, and keep `config.json` alongside it. `owner_id` and `local_id` identify provenance; they are not authentication keys.

### Uninstall

Ask Codex to remove N3MemoryCore after confirming a backup of `~/.n3mc/`. Remove the hook registration and Python environment first, then decide whether to retain or delete the saved database.

## ID Hierarchy

N3MemoryCore uses the following provenance fields. In addition, Codex supplies `turn_id` to associate the prompt and final reply from one turn; it is different from the record `id`.

| ID | Stored in | Generated | Granularity | Purpose |
|---|---|---|---|---|
| `id` (PK) | DB record | Per record (UUIDv7, time-ordered) | **One record** | Unique identifier for each memory — used for deletion and dedup |
| `owner_id` | `config.json` | First startup (UUIDv4) | **Owner / N3MC server** | Identifies whose data this is — for shared/multi-user scenarios and import provenance |
| `session_id` | In-memory or supplied by host | Supplied by Codex as `thread_id` | **Task / project / conversation** | Groups memories that belong to one task / project / conversation. In Free, drives the `b_session` ranking bias (match=1.0, mismatch=0.6) so the ongoing exchange ranks above unrelated past sessions |
| `local_id` (agent_id) | `config.json` / API | First startup (UUIDv4), or per request | **Agent / install** | UUIDv4 identifier for the speaking agent. Each agent gets its own UUID in multi-agent setups (in Free, stored but not used in ranking; `b_local` is a Pro feature) |
| `agent_name` | DB record | Per buffer call (free-form string) | **Agent display name** | Human-readable label for the agent (e.g. `"codex"`) |

```
owner_id  (one N3MC server / data owner)
  └── session_id  (one task / project / conversation)
        └── local_id  (the speaking agent within that session)
              ├── agent_name  (its display name: "codex", etc.)
              └── id  (one memory record)
```

## Requirements

- **Codex** with UserPromptSubmit and Stop hook support and a way to inspect/trust the commands
- **Python 3.10+**
- **Validation**: Reference-code tests ran on Windows / Python 3.12. The user reported successful instruction-based generation and manual checks ①–③ in Hyper-V. Automatic hook capture and recall in a fresh Codex chat, and Linux/macOS operation, have not been verified.

> To check if Python is installed, run `python --version` in your terminal.
> If missing, Codex will guide you during setup.

## Extensibility

N3MemoryCore is built from a specification, so extending it is as simple as asking Codex.

- **MCP server** — Expose N3MC as an MCP server so other AI tools can access the memory
- **PostgreSQL migration** — Move from SQLite to PostgreSQL + pgvector for team-scale deployments
- **Custom search logic** — Tune bias coefficients and ranking formulas
- **Alternative embedding models** — Swap in a different model to suit your use case
- **Keyword-search tokenizer** — The default FTS5 `trigram` tokenizer was chosen because it works both for languages written without spaces (Japanese, Chinese, …) and for languages like English (this project targets multilingual conversations). Adapt the final tokenizer to your own language and environment (e.g. `porter unicode61` to fold English word forms, or a morphological analyzer for higher Japanese precision). Codex can do it for you, including rebuilding the existing DB's FTS index
- **Custom ID fields** — Add fields like `project_id` or `tag` to organize memories your way
- **PDF import** — Extract text from PDF files and store them as searchable memories
- **Hashtag support** — Codex auto-tags memories with `#hashtags` for filtered search (e.g. `--search "#AWS"`) — works with existing FTS, no DB changes needed

These are customization ideas, not features already supplied by this edition. Load the specification into Codex, describe the change, and validate the resulting implementation.

## ⚠️ Disclaimer

- **No support, no claims**: This project is provided as-is with no support. Questions, bug reports, and feature requests are not guaranteed a response. Use entirely at your own discretion.
- **Use at your own risk**: This system runs on AI-generated code. The author is not responsible for any data changes or issues caused by its use.
- **Backup first**: Always back up your current environment before running this on important projects.

---

Apache License 2.0 — Copyright (C) 2026 NeuralNexusNote™ / ArnolfJp019
See [LICENSE](./LICENSE) for details.
