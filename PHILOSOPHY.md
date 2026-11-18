# N3MemoryCore Free for Codex — Development Philosophy

[日本語](#開発理念)

## The instruction-led approach

N3MemoryCore is a local memory and retrieval system for Codex. The [English](N3MemoryCore_v1.9.0_Free_EN.md) and [Japanese](N3MemoryCore_v1.9.0_Free_JP.md) instruction documents describe the v1.9.0 build. Give one instruction document to Codex in a dedicated empty folder to generate an implementation for your environment. Confirm the installation folder before allowing changes, then inspect and trust the hooks and check saving and recall in a new chat.

The repository also contains a reference implementation. Its later CPU, lifecycle and recovery features are documented in the [README](README.md). They are not part of the v1.9.0 instruction documents. Choose one installation path and verify the resulting build before relying on it.

The lasting asset is the design expressed by the instructions. The code gives you an implementation you can run, inspect and change. Keep a backup of your local memory data when rebuilding or replacing that code.

> Code is the shadow; the instruction is the light.

The software and instructions are available under the Apache License 2.0.

---

# 開発理念

N3MemoryCoreはCodex用のローカル記憶・検索システムです。[日本語](N3MemoryCore_v1.9.0_Free_JP.md)と[英語](N3MemoryCore_v1.9.0_Free_EN.md)の指示書はv1.9.0の構築方法を定めています。専用の空フォルダーでCodexに指示書を渡し、実装先を確認したうえで、生成されたフックを確認・信頼し、新しいチャットで保存と想起を確かめます。

リポジトリには参考実装も含まれます。その後に加えたCPU動作、訂正・忘却、復元の機能は[README_JP](README_JP.md)で案内しており、v1.9.0の指示書には含まれません。導入経路を選び、その結果できた実装を確認してから利用してください。

指示書に表した設計は、環境に合わせて実装を作るための資産です。コードは実行・調査・変更できる実装です。作り直しや入れ替えの前には、ローカルの記憶データをバックアップしてください。

> コードは影であり、指示は光である。

ソフトウェアと指示書はApache License 2.0で提供します。
