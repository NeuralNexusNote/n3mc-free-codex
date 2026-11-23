# N3MemoryCore Free / Codex setup

[日本語](README_JP.md) · [Regeneration specification](N3MemoryCore_v1.9.1_Free_EN.md)

N3MemoryCore Free saves prompts and final replies from local Codex. It searches the local SQLite database when you submit a prompt, so a new chat can use relevant earlier records.

```sh
python -m pip install -e ".[test]"
n3mc --init
```

Run these commands from the Free source repository in the Python environment you intend to keep. Review and trust both handlers in `/hooks` and open a new chat. To regenerate the Free package, give Codex the linked specification and ask it to implement the package in a dedicated directory.

Data is stored in `~/.n3mc` by default, overridable through `N3MC_HOME`. The hook passes relevant records into the chat. It skips opt-out turns and detected credentials. Records have no expiration policy.

Registration uses `$CODEX_HOME/hooks.json`, defaulting to `~/.codex/hooks.json`. Before relying on capture, verify multiple turns and a separate chat. Set `N3MC_CODEX_HOOKS_PATH` to isolate registration in tests.

Use **Sol** for implementation and debugging and **Astra** for reviewing a regenerated build.

## Features

| You want to… | N3MemoryCore… | How |
|---|---|---|
| Find things in your own words | finds a past conversation even when the exact words differ | Vector search with `intfloat/multilingual-e5-base` (Japanese, English, Chinese, Korean and ~100 other languages) plus keyword search |
| Pick up tomorrow where you left off | keeps the memory across sessions and across project folders | One database for every folder; the conversation you are in is ranked first |
| Let several agents share one memory | keeps who wrote each record | `agent_name`, `local_id`. Ranking each agent's own memories first is a Pro feature |
| Move up later | builds a database that Pro can take over | Databases built from the same specification are compatible; Pro reads Free's with `n3mc-pro --migrate-from-free` |

To use another embedding model, set it in `config.json` and run `n3mc --reembed`; the model must produce 768-dimension vectors.

## ⚠️ Disclaimer

- **No support, no claims**: This project is provided as-is with no support. Questions, bug reports, and feature requests are not guaranteed a response. Use entirely at your own discretion.
- **Use at your own risk**: This system runs on AI-generated code. The author is not responsible for any data changes or issues caused by its use.
- **Backup first**: Always back up your current environment before running this on important projects.

---

Apache License 2.0 — Copyright (C) 2026 NeuralNexusNote™ / ArnolfJp019
See [LICENSE](./LICENSE) for details.
