# N3MemoryCore Free v1.9.0 CLI 逐条照合（2026-11-18）

対象: `N3MemoryCore_v1.9.0_Free_JP.md` と `n3memorycore/n3memory.py`、`codex_entry.py`、`codex_install.py`。入出力はコードと隔離した SQLite テストで確認した。実モデルを伴う検索速度と Codex 画面でのフック信頼・複数ターンは、この照合には含めない。

| コマンド | 指示書の入力・出力 | コードとの照合結果 |
| --- | --- | --- |
| `--init` | データ・設定を作り、Codex の UserPromptSubmit / Stop を `hooks.json` に登録。既存設定を保ち、変更時はバックアップ。不正 JSON は終了 1。 | `cmd_init` → `codex_install.install` で実装。隔離した `hooks.json` の冪等テスト通過。信頼操作は Codex 上で別途必要。 |
| `--buffer TEXT` / `--buffer -` | 引数または stdin を保存。`--agent-id` は表示名。完全一致は重複保存しない。サーバー失敗時は直接 SQLite へ保存。 | 実装済み。未知の `/buffer` 応答で黙って終了する差分を修正し、直接保存へフォールバック。 |
| `--search QUERY` | Markdown の検索結果を stdout に出す。`--since` / `--until` を受け付け、読めない日時は stderr と終了 2。 | 実装済み。日時境界テスト通過。モデルを使う実検索の速度は未測定。 |
| `--repair` | サーバーに上限なしの `/repair` を送り、修復件数を stderr に表示。 | 実装済み。`status:error` を無視する差分を修正して stderr に報告。 |
| `--reembed` | 設定モデルで全件を 200 件ずつ再埋め込み。中断後に再開。次元不一致は終了 1。進捗は stderr。 | 実装済み。置換・再開の隔離テスト通過。 |
| `--list` | DB を直接読み、既定は 4 列 TSV と `Total`。`--since` / `--until`、`--format jsonl` 対応。 | JSONL に非 JSON の `Total` が混ざる差分、TSV の content 内タブで列が増える差分を修正。 |
| `--recall-thread TURN_ID` | 指定ターンと同じチャットの前後各 2 ターン（件数変更可）。TSV / JSONL。 | DB が他チャットのターンを混ぜる差分を修正。JSONL の `Total` と TSV 内タブも修正。 |
| `--show-turn TURN_ID` | 同一ターンの質問、回答を順に全文表示し、件数を出す。 | 実装済み。複数行の全文とロール順を隔離 DB で確認。 |
| `--stop` | 古い一時ファイルの削除と監査ログのローテーション。 | Codex 用 `cmd_stop` で実装。後片付け失敗の stderr 通知をテスト。 |
| `--hook-submit` | フック内部用。JSON の質問を検索・保存。Codex の `thread_id` / `turn_id` を使う。 | `codex_entry --prompt` から呼び出される。旧ホスト向けトランスクリプト復旧は Codex の通常経路では使わないため、指示書の矛盾を訂正。 |
| `--save-claude-turn` | フック内部用。JSON の回答を同じ `turn_id` で保存。 | `codex_entry --stop` から呼び出される。保存拒否・資格情報検出ターンのスキップは統合テスト通過。 |
| `--run-server` | ローカル FastAPI サーバーを起動。 | `run_server` が `uvicorn` を起動する実装を確認。常駐プロセスの実起動は本照合では未実施。 |

追加オプション `--before` / `--after` / `--format` / `--agent-id` / `--since` / `--until` は上表の各コマンドとの組み合わせを確認した。`n3mc` コンソールスクリプトはこの実装先の `.venv` にインストールして起動を確認した。

テスト: `tests/test_cli_contract.py`、`test_database.py`、`test_codex_integration.py`、`test_index_meta.py`、`TestTimeBounds`、`TestHousekeeping` のモデル不要部分で **58 passed**。

指示書の JP / EN Markdown を更新し、原本の `docs_markdown/*.md` とルートの `*.txt` を各言語でバイト一致にした。Codex のフックが信頼済みか、新しいチャットで複数ターン保存されるかは未確認。
