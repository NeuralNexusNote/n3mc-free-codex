# N3MemoryCore Free クロスセッション実行確認（2026-11-18）

隔離データ領域: `C:\Users\ttake\Codex\n3mc-free-codex\test_artifacts\cross_session_20261118`。既存の `~/.n3mc` は使用していない。ローカル検索サーバーはポート 62211、モデルは `intfloat/multilingual-e5-base`。モデルの外部ダウンロードを避けるため `HF_HUB_OFFLINE=1` と `TRANSFORMERS_OFFLINE=1` を設定した。

1. セッション1（独立した CLI プロセス）で `.venv\Scripts\n3mc.exe --buffer 'クロスセッション検証の合言葉は銀河ペンギン7319です。'` を実行し、終了コード 0。別プロセスの `--list --format jsonl` でも該当レコードを確認した。
2. セッション2（別の CLI プロセス）で `.venv\Scripts\n3mc.exe --search '銀河ペンギンの合言葉は？'` を実行し、終了コード 0。標準出力に以下を確認した。

```text
# Recalled Memory Context
Search query: 銀河ペンギンの合言葉は？

## Top matches (use these to answer the question)

## [1] score=0.1800 saved=2026-11-18 10:45 (UTC+0900) -
クロスセッション検証の合言葉は銀河ペンギン7319です。
```

通常の制限付き実行環境では `127.0.0.1` の接続が `WinError 10013` で拒否され、初回の `--search` は「memory server is still starting」と表示された。ローカルソケットを許可した実行で同じ隔離領域を使用すると、上記の検索結果を得られた。これは実行環境の制限で、N3MemoryCore の検索データ欠落ではない。

試験用サーバーには `_request_shutdown` を送り、`True` を確認した。制限付き実行時に残った試験用 PID ファイルは、対象プロセスが存在しないことを確認して削除した。コードの修正は不要。
