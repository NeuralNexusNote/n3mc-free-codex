# N3MemoryCore Free for Codex v1.9.1

[English](N3MemoryCore_v1.9.1_Free_EN.md)

ローカルの Codex にチャットをまたぐ永続記憶を実装する。実装・デバッグは **Sol**、コードレビューは **Astra** を推奨する。モデルは利用できるものを確認して選ぶ。

## 1. セットアップと再作成

1. 専用フォルダに Python 3.10 以上を用意する。再作成では、ソースと未コミットの変更を退避してからパッケージを入れ替える。個人データと Codex の設定はソースツリーの外に置く。
2. 再作成する場合は Codex に本書を渡し、そのフォルダへの実装を依頼する。リファレンス実装を使う場合は既存リポジトリを使う。いずれもソースのルートで `python -m pip install -e ".[test]"` を実行する。
3. まず `N3MC_HOME` と `N3MC_CODEX_HOOKS_PATH` に一時パスを指定し、空いているループバックポートを使って §6 のテストを行う。
4. ローカルの Codex で有効にするには、使い続ける Python 環境から `n3mc --init` を実行する。デスクトップ版の **設定 → Hooks**、または CLI の `/hooks` で両フックを確認して信頼する。利用者が実際に行うテストは §6.1–6.2 に従う。

## 2. パッケージとデータ

- 配布名 `n3memorycore-free-codex`、バージョン `1.9.1`。setuptools を使用する。実行時依存は `fastapi`、`uvicorn`、`pydantic`、`sqlite-vec`、`sentence-transformers`、`uuid7`、`psutil`。テスト追加依存は `pytest` と `httpx`。
- `n3memorycore/` に CLI・サーバーの `n3memory.py`、`paths.py`、`codex_entry.py`、`codex_install.py`、`maintenance.py`、`core/{database,processor}.py` を置く。テスト、`pyproject.toml`、`AGENTS.md`、日英の README と指示書を含める。
- エントリポイントは `n3mc → n3memorycore.n3memory:main`、`n3mc-hook → n3memorycore.codex_entry:prompt_main`、`n3mc-stop-hook → n3memorycore.codex_entry:stop_main`。
- データの既定値は `~/.n3mc`。`N3MC_HOME` で変更できる。`config.json` と `.memory/n3memory.db` を一緒に保全する。稼働中の DB は SQLite のオンラインバックアップを使うか、対象サーバーを停止してからコピーする。既存の所有者 ID、スキーマ、インデックスメタデータを維持する。
- コードフェンスを `[code omitted]` に置き換える。段落、文、固定長（400 文字、重なり 40 文字）の順で分割し、分割後の全チャンクを保存する。既存 DB との互換性のため `[user]` と `[claude]` の記録形式を維持する。新規フックレコードの出所は `agent_name=codex`。
- 既定の CPU モデルは `intfloat/multilingual-e5-base`（768 次元）。初回は重みのダウンロードが発生する場合がある。モデルが使えない間も本文を保存し、FTS 検索と後続のインデックス修復を使う。
- Codex の既定値は `min_score=0.2`、`min_results=0`、`context_max_chars=12000`。`semantic_rescue_enabled=true`、`semantic_rescue_min_cos=0.80`、`semantic_rescue_margin=0.02` を使う。以下の従来の技術仕様に異なる既定値がある場合はここを優先する。


## ⚠️ 免責事項・配布条件

本ソフトウェアおよび本指示書は **現状有姿（AS-IS）** で提供されます。

- **ノーサポート**: 作者はバグ修正・質問対応・動作保証などの一切のサポートを提供しません。
- **ノークレーム・無保証**: 本ソフトウェアの使用によって生じたいかなる損害（データ損失、業務停止、第三者への損害等）についても、作者は一切の責任を負いません。
- **自己責任**: 利用者は本ソフトウェアをご自身のリスクと判断のもとで使用してください。
- **変更・廃止**: 作者はいつでも予告なく本ソフトウェアを変更・廃止できます。

本ソフトウェアを使用した時点で、上記条件に同意したものとみなします。

- **使用許諾**: Apache License 2.0。詳細は LICENSE ファイルを参照してください。

> **削除（アンインストール）**: N3MemoryCore を削除する場合は、フォルダを直接削除せず、Codex に「N3MemoryCore を削除してください」と依頼してください。フック設定の解除も含めて安全に処理されます。
> **削除前のバックアップ**: 記憶を引き継ぐ場合は削除前に以下の2ファイルを保存してください。`n3memory.db`（記憶データ）と `config.json`（`owner_id`・`local_id` の UUIDv4 キーを含む）はセットで保管する必要があります。キーが一致しないと記憶の所有者検証や環境分類が正しく機能しません。

> **実装上の疑問について**: 作者への問い合わせはできませんが、本指示書を Codex に読み込ませて質問することで、実装・カスタマイズの支援を受けることができます。
> **カスタマイズについて**: カスタマイズする時は Codex に指示書の場所を教えて「指示書も直してください。」と言ってください。この指示書もそのようにして作成されました。

---

## 3. 技術仕様（一切の変更禁止）

> **⚠️ AI自動変更禁止**: 以下の仕様をAIが速度向上・最適化を理由に自律的に変更してはならない。埋め込みモデル・次元数・同期書き込み設定の変更は、人間が `config.json` を手動編集することでのみ許可される。

### ID 階層構造

N3MemoryCore は 6 つの ID フィールドで各レコードの出所と文脈を識別する：

| ID | 保存場所 | 生成タイミング | 粒度 | 用途 |
|---|---|---|---|---|
| `id` (PK) | DB レコード | レコード作成時 (UUIDv7, 時系列順) | **1 レコード** | 各記憶の一意識別子 — 削除・重複検出に使用 |
| `owner_id` | `config.json` | 初回起動時 (UUIDv4) | **所有者 / N3MC サーバー** | N3MC FastAPI インスタンス／データ所有者の識別 — 共有・マルチユーザーシナリオやインポート時の出所保持に使用 |
| `session_id` | ホストから供給（フック stdin JSON） または メモリ内フォールバック | 会話単位 | **タスク / プロジェクト / 会話** | 1 つのタスク・プロジェクト・会話スレッドに属する記憶をまとめて浮上させるためのグルーピングキー。Codex は UserPromptSubmit / Stop フックの stdin JSON に `session_id` フィールド（会話セッション ID）を供給するため、フックはこれを `/buffer` `/search` に転送する。他のホスト（独自タスク番号、Ollama 風 UI 等）も自前のセッション識別子を API で渡せる。ホストが `session_id` を供給しない場合、または CLI 直接呼び出し（フックを介さない）の場合は、`n3memory.py` 起動時に生成された UUIDv4 にプロセス単位でフォールバックする。Free 版・Pro 版ともに `b_session` ランキングバイアスを駆動する |
| `local_id` | `config.json` / API | 初回起動時 (UUIDv4)、またはリクエストごと | **エージェント / インストール** | 発話するエージェントの UUIDv4 識別子（1 つの Codex インストール = 1 つの `local_id`、同一 DB 上の異なるエージェントは別 UUID を持つ）。レコードに保存される。**Free 版では `b_local` は無効（常に 1.0）** — エージェント単位のランキング乗数は Pro 機能。下記「検索ランキングバイアス」を参照 |
| `turn_id` | Codex のフック入力 | ターン単位 | 入力と応答に同じ値を使う。手動保存は NULL を許す |
| `agent_name` | DB レコード | バッファ呼び出し時 (任意文字列) | **エージェント表示名** | エージェントの人間可読なラベル（例：`"codex"`）。`--buffer --agent-id <name>` オプションが設定するのは**この**フィールド（オプション名は互換のため残している。§3.7）。`local_id` を設定することはない |

**階層関係：**

```
owner_id  (データフォルダ ~/.n3mc とその持ち主: config.json、初回起動時)
  └── local_id  (インストール: config.json、初回起動時。どのセッションでも同じ)
        └── session_id  (Codex の 1 つの会話。フックが渡す。ないときはプロセスごとの UUIDv4)
              └── turn_id  (1 往復: 利用者の発言 1 つと、その返答)
                    └── id  (1 件のレコード = 1 チャンク、UUIDv7)

agent_name  (表示用のラベル。階層の外にある。フックは "codex")
```

`local_id` はセッションごとのエージェントではない。`config.json` に 1 回だけ書かれ、フックと CLI は送らないので、1 つのインストールのレコードはすべて同じ値を持つ（API の呼び出し側は、要求ごとに自分の `local_id` を渡せる）。長い発言は、同じ `turn_id` を持つ複数の `id` のレコードになる。Free では 1 つのインストールに DB が 1 つなので、`owner_id` と `local_id` はそれぞれ 1 つの値のままである。レコードを見分けるのに役立つのは、ほかの DB のレコードを取り込むとき（Pro）だけである。

**検索ランキングバイアス（Free 版）：**
- `session_id` 一致 → `b_session = 1.0`（不一致または NULL: `0.6`）— **タスク／プロジェクト単位で会話をまとめる**ことで、進行中のやり取りに属する記憶が無関係な過去セッションの記憶より上位に来る。Free 版では類似度・新鮮度に次ぐ主要ランキングシグナル。
- `local_id` — レコードに保存されるが、**Free 版のランキングには使用されない**。ローカルバイアス（`b_local`）は Pro 機能であり、Free 版では一致／不一致に関わらず `b_local` は常に 1.0。Pro 版では一致時 `b_local = 1.0`、不一致時 `b_local = 0.8` を適用し、同一 DB 上の他エージェントの記憶よりも自エージェントの記憶を追加で優先する。

### 埋め込み
- **デフォルトモデル**: `intfloat/multilingual-e5-base` / ベクトル: float[768]
- デフォルトを多言語モデルにしているのは意図的 — 日本語・英語・中国語・韓国語など 100 言語以上を箱出しでインデックス可能。単一言語で高精度を出したい場合はユーザー側でモデルを差し替える（後述「言語特化モデルへの切り替え」参照）。デフォルトリリースでは言語特化の判断をしない。
- 取得時は必ず `normalize_embeddings=True` を指定し、L2 正規化済みベクトル（norm=1）を保証せよ。
- **入力プレフィックス（必須）**: このモデルはプレフィックスなしでは精度が大幅に低下する。以下を厳守せよ:

```python
# 保存時（文書として登録）
text_to_embed = "passage: " + content

# 検索時（クエリとして照合）
text_to_embed = "query: " + keyword
```

#### 言語特化モデルへの切り替え（ユーザー側のカスタマイズ）

埋め込みモデルは `~/.n3mc/config.json` の `embed_model` フィールドで決まる（デフォルト `intfloat/multilingual-e5-base`。初回起動時にファイルへ書き込まれる）。**環境変数による上書きはない**（v1.5.0）: `config.json` には常に `embed_model` があるので、以前の版が記載していた `$N3MC_EMBED_MODEL` 変数は一度も効いていなかった。また §3 はモデルの変更を人間による `config.json` の編集だけに限っている。

**読み込みの失敗（v1.5.0）**: モデルを読み込めない場合（オフラインでの初回起動、Hugging Face のキャッシュがない、`embed_model` の綴り間違い）、保存や検索のたびに読み込みを再試行しない。失敗したあと 60 秒間（`MODEL_RETRY_SECONDS`）は `get_model()` が再試行せずにすぐ例外を出す。これにより、保存はそれぞれダウンロードの試行を待たずにベクトルなしのレコードに切り替わり（後の `--repair` で再インデックスされる）、検索は `embed_query` の警告（§5）付きでキーワードのみになる。失敗した試行ごとに stderr へ 1 行出す（多くても 1 分に 1 回）。

ユーザーが設定し得る例:

| 目的 | `embed_model` 値 | ベクトル次元 |
|---|---|---|
| 英語特化、若干高精度 | `intfloat/e5-base-v2` | 768 |
| 多言語、高精度（より遅く・大きい） | `intfloat/multilingual-e5-large` | 1024 |
| 日本語特化 | `cl-nagoya/sup-simcse-ja-base` | 768 |
| 英語、より小さく・高速 | `intfloat/e5-small-v2` | 384 |

**⚠️ ベクトル次元の制約**: `memories_vec` は固定の `float[768]` 次元で作成される。異なる次元のモデルへ切り替える場合は vec テーブルの再作成（および全レコードの再埋め込み）が必要。リファレンス実装は同一次元のモデル切り替えのみ手動介入なしでサポートする。

**アップグレード手順（同一次元のモデル切り替え）**:
1. `~/.n3mc/config.json` を編集 → `embed_model` を新モデル名に変更。
2. サーバー再起動（`_stop_stale_server` と同じやり方で止める — §3。PID ファイルの番号だけを頼りに止めない — か、次回 CLI 呼び出しで自動的に再起動される）。
3. 次回の `/repair` がモデルの食い違いを見つけ（`meta.embed_model`、§3.5「索引の情報」）、通知 `embed_model_mismatch` を出す。保存されたベクトルは旧モデルのままなので、作り直すまで検索品質は劣化する。
4. `n3mc --reembed` を実行する：すべての記録を新しいモデルで埋め込み直す（途中から再開できる。§3.5）。印を消して `n3mc --repair` を実行しても、ベクトルは作り直され**ない**：`--repair` は欠けたベクトルを足すだけである。

**⚠️ 異なる次元のモデル切り替え**: リファレンス実装では手動 SQL なしには非対応。`memories_vec` テーブルを drop → 新次元で再作成 → `meta` の `embed_model`・`embed_dim`・`embed_model_at` の行を削除 → `n3mc --reembed`。（`--reembed` だけでは、表と次元の違うモデルを受け付けない。）

### モジュール間インポート
`sys.path` ハックは使用せず、パッケージ相対インポートを使用すること。パッケージ内部:

```python
# n3memorycore/core/processor.py
from .database import (
    get_connection,
    init_db,
    insert_memory,
    search_vector,
    search_fts,
    get_all_memories,
    delete_memory,
    count_memories,
    check_exact_duplicate,
    find_unindexed_memories,
    serialize_vector,        # /repair エンドポイントで必須
    get_memories_by_turn_id, # Q-A pairing で必須
    strip_fts_punctuation,   # /repair の FTS マイグレーションで必須
)
```

```python
# n3memorycore/n3memory.py
from .paths import HOME_DIR, MEMORY_DIR, DB_PATH, PID_FILE, AUDIT_LOG, CONFIG_FILE, NOTICES_FILE, claude_paths
from .core.database import (
    get_connection, init_db, migrate_schema, insert_memory, insert_memory_once,
    check_exact_duplicate, search_vector, find_unindexed_memories,
    strip_fts_punctuation, serialize_vector,
)
from .core.processor import (
    embed_passage, cosine_sim_from_l2, hybrid_search,
    chunk_text, add_chunk_prefixes, purify_text, render_memory_context,
)
```



### 常駐型 FastAPI サーバー
- **ポート**: デフォルト `18520`（`config.json` の `server_port` で変更可）。同じ PC で別の N3MC（Pro 版など）を動かすときは、フォルダごとに `server_port` を分けること。
- **待ち受けアドレス**: `bind_host`（既定 `127.0.0.1`）。**既定のまま使うこと。** サーバーの API（検索・一覧・`/shutdown` 等）には認証がないため、ほかの値にするとネットワークから届く。`127.0.0.1` 以外が設定されていたら、起動時に stderr へ警告を出す。
- **起動タイミング**: `n3mc` のいずれかのサブコマンド（または `python -m n3memorycore.n3memory`）の実行時、下の「サーバーの確認と入れ替え（`ensure_server`）」に従い、必要なら `python -m n3memorycore.n3memory --run-server` として自動的にバックグラウンド起動せよ。PID ファイルの書き込みはアトミック操作（例: `open(..., 'x')` 排他作成フラグ）を使用し、複数プロセスの同時起動を防止すること。
- **通信方式**: HTTP over TCP (`http://127.0.0.1:{port}`)。**プロキシを通さない**（2026-11-18 の最終レビュー、F16）：`_post` / `_get` は、`urllib.request.urlopen` ではなく `urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=…)` で要求を開く。既定の opener は `HTTP_PROXY` やシステムのプロキシ設定に従う。プロキシがあり、`NO_PROXY` に `127.0.0.1` がないと（社内の PC ではふつうにある）、要求がすべてプロキシに送られ、サーバーがないと判断され、フックのたびにサーバーの起動を待ち、検索は「still starting」になり、保存はベクトルなしの直接保存になっていた。
- **Host ヘッダーの確認（v1.5.0）**: すべてのエンドポイントは、リクエストの `Host` ヘッダーが `127.0.0.1:<port>` または `localhost:<port>` でなければ 403 を返す。そうしないと、ユーザーのブラウザで開いた Web ページが DNS リバインディング（127.0.0.1 に解決される名前）でサーバーに届き、`GET /list` を読めてしまう。CLI は常に `Host: 127.0.0.1:<port>` を送る。FastAPI の `TestClient` は `testserver` を送るので、テストではヘッダーを明示するか、確認を差し替える。**`<port>` は、このサーバーのプロセスが待ち受けているポート**（起動時に読んだ `server_port`）で、いまの `config.json` の値ではない。利用者が `server_port` を変えたあとも、古いサーバーが自分のポートで `/health` と `/shutdown` に答えられないと、CLI が止められない（下の「PID ファイルの扱い」）。
- **`Origin` ヘッダー付きのリクエストを断る（v1.9.1）**: リクエストに `Origin` ヘッダーがあれば、値に関係なく（`null` を含む）、すべてのエンドポイントは 403 を返す。`Origin` のないリクエストには、上の `Host` の確認がそのまま働く。ブラウザは、Web ページが別のサイトに送るリクエスト（`fetch`、フォームの POST）に `Origin` を付ける。サーバーは `127.0.0.1` で認証なしに待ち受けるので、ユーザーが開いたページからリクエストを送れてしまい、`Host` の確認では止まらない（その `Host` は `127.0.0.1:<port>` になる）。CLI、フック、テストのクライアントは `Origin` を送らないので、それらの動きは変わらない。この確認は `Host` の確認と同じ場所で、どのエンドポイントの処理よりも前に行う。
- **エンドポイントでイベントループを止めない（v1.5.0）**: 埋め込みや DB を扱うエンドポイント（`/buffer`・`/search`・`/repair`・`/list`）は `async def` ではなく普通の `def` で定義し、FastAPI のスレッドプールで動かす。これで長い `/repair` の間も `/health` が応答し続ける。（v1.4.0 では中で同期処理をする `async def` だったため、長い `/repair` の間 `/health` がタイムアウトし、CLI がサーバーなしと判断して起動・入れ替えの処理に入っていた。）エンドポイントが使う SQLite 接続はそのエンドポイントの呼び出しの中で開き（リクエストごとに 1 接続）、スレッドをまたいで共有しない。
- **死活監視**: CLI実行のたびに `/health` エンドポイントへPINGし、応答の中身でサーバーが自分のものか・最新のコードか を判定せよ（下記）。

#### サーバーの名乗り（`/health`）

`GET /health` は次を返す:

```json
{"status": "ok", "root": "<HOME_DIR の絶対パス>", "code_version": "<16桁>", "pid": 12345}
```

- `root`: そのサーバーのデータフォルダ（`$N3MC_HOME` または `~/.n3mc`）の絶対パス。比較は `os.path.normcase(os.path.abspath(...))` で行う。
- `code_version`: `n3memorycore/n3memory.py`・`core/database.py`・`core/processor.py` のファイル内容と、`config.json` の中身（JSON として読めたら、キーの順に並べ直して `json.dumps(..., sort_keys=True)` したもの。読めなければ生のバイト列）をまとめた SHA-256 の先頭 16 桁。**空白やキーの順だけの違いでは変わらない。** `_load_config` が `config.json` を書き直した場合は計算し直す。**サーバーは自分の `code_version` を、動くための設定に `_load_config` が使ったのと同じ `config.json` の内容（読んだバイト列。キーを補って書いたときは書いた内容）から計算し、ファイルを開き直さない。** そのため、その読み取りのあとに変えると、クライアントの値と違い、サーバーは stale として入れ替わる（2026-11-22、レビュー #9：2 回目の読み取りがあると、その間に変えたとき、古い設定で動くサーバーが新しいハッシュを返し、入れ替わらず、変更が反映されなかった）。
- `pid`: サーバープロセスの PID。

#### サーバーの確認と入れ替え（`ensure_server`）

CLI は `/health` の応答を次のように判定する（`_health_decision(health)`。戻り値は `'ok'`・`'stale'`・`'foreign'`・`'legacy'`・`'none'` のどれか）。この確認をするのは、サーバーを使うコマンド（`--buffer`・`--search`・`--repair`・`--hook-submit`・`--save-claude-turn`）だけで、自分の DB を直接読む `--list`・`--recall-thread`・`--show-turn` と、`--stop`・`--init` では行わない:

| 応答 | 判定 | 動作 |
|---|---|---|
| `root` が自分と同じ、`code_version` も同じ | 正常 | そのまま使う |
| `root` が自分と同じ、`code_version` が違う | 自分の古いサーバー | 止めて起動し直す |
| `root` が自分と違う | 別のフォルダのサーバー | **止めない。使わない。** 下記「ポートが別のフォルダのサーバーのとき」 |
| `root` を返さない（v1.3.x 以前のサーバー） | 確かめが要る | psutil で自分のサーバーだと確かめられたら止めて起動し直す。確かめられない（または止められない）ときは別のフォルダのサーバーと同じ扱い（`_FOREIGN_SERVER_ROOT` には `(unknown: the server did not report its folder)` を入れ、知らせ `port_conflict` を出す） |
| 応答なし | サーバーなし | 下記「PID ファイルの扱い」 |

- **止め方（`_stop_stale_server`）**: まず `POST /shutdown`（本文 `{"root": "<自分の HOME_DIR>"}`）を頼む。v1.3.x のように `/shutdown` を持たないサーバーにだけ、psutil で確かめてからプロセスを終了する。**PID ファイルの番号では止めない**（別のプロセスに使い回されている可能性がある）。
- **psutil での確かめ（`_is_own_server_process`）**: PID は `/health` の `pid`、それがなければポートで待ち受けているプロセス（`psutil.net_connections`）から得る。そのプロセスのコマンドラインに `n3memorycore.n3memory` と `--run-server` があり、環境変数 `N3MC_HOME` から解いたデータフォルダが自分の `HOME_DIR` と同じときだけ「自分のサーバー」とする。psutil が入っていない・権限がない・どれかが一致しない、のときは「確かめられない」。
- 確かめられないときは止めず、「古いサーバーを止められない。同じ `server_port` を別の N3MC のフォルダが使っている可能性もある。各フォルダの `config.json` の `server_port` を確かめ、手で起動し直すこと」という知らせ（`stale_server`）を出す。自分の古いサーバー（`root` が同じ）を止められなかったときは、同じ DB を使っているので、そのまま使い続ける（`ensure_server` は True）。
- **PID ファイルの扱い**: `/health` が応答しないとき、PID ファイルの番号のプロセスが**このフォルダのサーバーだと確かめられたとき（起動中）だけ**、PID ファイルを残したまま `/health` を最大 60 秒（0.5 秒間隔）見て待つ。60 秒たってもまだ起動中なら（初回起動はモデルのダウンロードで 2〜10 分かかる）、**別のサーバーを起動せず、PID ファイルも消さない**。このコマンドはサーバーなしで進め（保存は `_buffer_direct` へ、Codex フックの検索はローカル FTS（§4）、CLI は起動中であることを表示）、次のコマンドでまた確かめる。この最大 60 秒の待ちはフックの中で起きるので、`--init` は 2 本のフックを `"timeout": 120` で登録する（§4「フックの制限時間」）。それ以外（番号のプロセスが死んでいる、別のプロセスに使い回されている）は、待たずに PID ファイルを消して起動する。
  - **サーバーが別のポートにいるとき（2026-11-20）**: 待つ前に、確かめたそのプロセスが、いまの `server_port` 以外のポートで待ち受けていないかを調べる（psutil で、その PID の `LISTEN` の接続）。サーバーが動いている間に利用者が `server_port` を変えると、こうなる。新しいポートの `/health` はずっと答えないので、この確認がないと、コマンドのたびに 60 秒待ち、サーバーはいつまでも起動しない。そうしたポートのうち `/health` がこのフォルダの `root` を返すものに `POST /shutdown`（本文 `{"root": "<自分の HOME_DIR>"}`）を送り、プロセスが終わるのを最大 15 秒待ち、PID ファイルがまだその PID を持っていれば消し、待たずにいまのポートでサーバーを起動する。`/health` が答えないポートや、別の `root` を返すポートには何もしない。PID ファイルの番号でプロセスを止めないことは変わらない。起動中のサーバーはまだどのポートでも待ち受けていないので、上の 60 秒の待ちはそのまま働く。
- **psutil は必須（v1.5.0）**: 上の PID ファイルの確かめには psutil が要る。psutil がないと、v1.4.0 は起動中のサーバーを一度も確かめられず、モデルの読み込み中にコマンドのたびに PID ファイルを消して別のサーバーを起動していた（`open(..., 'x')` による防止はこの削除で効かなくなっていた）。それでも `import psutil` に失敗した場合（壊れたインストール）は、PID ファイルの更新時刻から 60 秒間は PID ファイルのプロセスをすべて「起動中」、それ以降は死んでいるものとして扱う。作られてから 60 秒未満の PID ファイルがある間は、2 つ目のサーバーを決して起動しない。
- 自分で起動したサーバーが応答した時点で、`stale_server`・`port_conflict`・`server_start_failed` の知らせを消す。

#### サーバーの起動（`_start_server`、v1.5.0）

0. **起動する前に起動を予約する（2026-11-22、レビュー #5）**：`Popen` の前に `open(..., "x")` で PID ファイルを作り、`Popen` が返るまで空のままにし、返ったら子プロセスの PID を書く。`FileExistsError` なら、ほかのプロセスがサーバーを起動している（または動かしている）：起動せず、上の「PID ファイルの扱い」に従う。`Popen` が例外を出したら、予約を消す。**空か読めない PID ファイル**（予約から書くまでの間）は、ファイルの更新時刻から 60 秒の間「起動中」として扱い、死んだプロセスとは扱わない。消さず、2 つ目のサーバーも起動しない。60 秒を過ぎたら死んだものとして扱う。Windows で起動用 Python とサーバーの PID が異なる場合は、`/health` の応答が自分のデータ先とコードに一致し、返された PID が予約したプロセスの子であることを確認してから、PID ファイルを実際のサーバー PID に置き換える。（それまでは `_start_server` が先に `Popen` を呼び、そのあとで PID ファイルを作り、あれば上書きしていた。同時に動いた 2 つのフックがどちらもサーバーを起動し、モデルを 2 回読み込み、2 つ目はポートを取れずに失敗し、PID ファイルがその失敗したプロセスを指すことがあった。）
1. 下の「Clean CLI」のとおり `subprocess.Popen` で `python -m n3memorycore.n3memory --run-server` を起動する。stdout と stdin は `DEVNULL`、**stderr は `.memory/server.log` に追記する**（ファイルが 1 MB を超えていたら起動前に切り詰める）。サーバーはフックのプロセスから**切り離し**、フックが終わっても動き続けるようにする: Windows では `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW`、それ以外では `start_new_session=True`。
2. `/health` を 0.5 秒ごとに最大 60 秒見る。**待っている間に子プロセスが終了したら（`proc.poll() is not None`）、すぐに待つのをやめる** — ポートを N3MC 以外のプログラムが使っている、依存パッケージがない、DB を開けない、などの場合。**応答は、`ensure_server` と同じ確認を通ったときだけ使う**（2026-11-20 の 2 回目のレビュー）：`root` がこのフォルダであること（「ok」、または「stale」— このフォルダの、コードの違うサーバーで、次の呼び出しが入れ替える）。別のフォルダのサーバーが答えたとき（同じ `server_port` の 2 つのフォルダを同時に起動し、もう一方が先にポートを取った）や、`root` を返さないサーバーのときは、決して使わない。`_FOREIGN_SERVER_ROOT` を設定し、上の表と同じ `port_conflict` を出し、サーバーなしで進む（保存は `_buffer_direct`、Codex フックの検索はローカル FTS（§4））。この決まりの前は、どんな応答でも待ちを終え、その呼び出しの検索と保存が別のフォルダの記憶に向かった。
3. そうして早く終了したときは、知らせ `server_start_failed`（"The N3MC memory server could not start (exit code <n>). See <path of server.log> for the reason."）を出し、時刻を `.memory/server_start_failed`（マーカーファイル）に書き、PID ファイルが終了したその子プロセスの PID を持っていれば消し、サーバーなしで進める（直接保存 / `memory search unavailable`）。`Popen` そのものが例外を出したときも、サーバーなしで進む（stderr に 1 行。知らせとマーカーは書かない）。
4. `.memory/server_start_failed` が作られてから 5 分未満の間は、サーバーの起動を試み直さず、そのままサーバーなしの処理に進む。これにより、壊れた環境でフックのたびに最大 60 秒かかることを防ぐ。サーバーが応答したらマーカーを消し、知らせも消す。
5. 60 秒たっても子プロセスが生きていれば、まだ起動中（モデルのダウンロード）なので、そのまま動かしておき、上の「起動中」の決まりに従う。
6. フックは `"timeout": 120` で登録する（§4「フックの制限時間」）。この最大 60 秒の待ちと、そのあとの保存が、Codex にフックを止められる前に終わるようにするため。

> **⚠️ 理由（v1.5.0、Free v1.4.0 のレビューで見つかった）**: v1.4.0 は子プロセスを見ずに 60 秒待ち切り、その stderr を `DEVNULL` に捨てていた。ポートが別のプログラムに使われていたり、サーバーが起動時に落ちたりすると、フックのたびに 60 秒止まり、理由もどこにも残らなかった。

#### `/shutdown`

`POST /shutdown`（本文 `{"root": str}`）。`root` がサーバー自身の `root` と同じときだけ `{"status": "ok"}` を返し、応答を返し終えたあとに自分で終了する（PID ファイルが自分の PID なら消す）。違えば 403。テストでは本物のサーバーに送らないよう、`_request_shutdown` と `_post` を必ず差し替えること。

#### ポートが別のフォルダのサーバーのとき

`ensure_server` は False を返し、モジュール変数 `_FOREIGN_SERVER_ROOT` にそのサーバーの `root` を入れ、知らせ `port_conflict` を出す。このとき **記録が別のフォルダの DB に混ざらないように**:

- 保存（フック・`--buffer`・`--save-claude-turn`）は自分の DB に `_buffer_direct` で直接書く（埋め込みは、自分のサーバーが動いたときの `/repair` で付く）。
- Codex の入力フックは自分の SQLite に対し FTS 検索を行う（§4）。CLI の `--search` はこの状態を次の形式で表示する。 `# Recalled Memory Context\n\n_(memory search unavailable: another N3MC folder's server is using port <port>)_\n`。
- `--repair` は何もせずに戻り、理由を stderr に 1 行出す。`/repair` も送らない。
- `--list`・`--recall-thread`・`--show-turn` はもともと自分の DB を直接読むので、そのまま動く。

#### 知らせ（`_notify`）

人が何かをする必要がある知らせ（`stale_server`、`port_conflict`、`server_start_failed`、`config_unreadable`、`config_type`、`db_corrupt`、`behavior_md_edited:<hash>`）は `_notify(key, message)` で出す:

1. stderr に出す。
2. `audit.log` に `{"ts", "hook": "notice", "key", "message"}` を記録する（同じ key・同じ文面は 1 回だけ）。
3. `.memory/notices.json` に残し、検索結果の先頭（検索結果では `Search query:` の行の直後、それ以外の出力では見出し `# Recalled Memory Context` の直後）に **1 日 1 回**（前回出してから 24 時間たったら） `> ⚠️ N3MC notice: <message>` として出す（`_take_notices`）。
4. 原因がなくなったら `_clear_notice(key)` で消す。
5. `notices.json` は `config.json` と同じく（§3.5）アトミックに書く（同じフォルダの一時ファイル + `os.replace`）。

テストでは `NOTICES_FILE` と `AUDIT_LOG` を必ず一時フォルダに向けること（本物の `~/.n3mc` に書かない）。
- **応答目標**: 0.7s 前後（埋め込み生成 + DB検索の合計）。ハードウェア・OS・モデルキャッシュ状態に依存するため、達成目標として扱い厳密な要件とはしない。
- **初回起動**: モデルのプリロードを uvicorn 起動前に実行するため、初回に限らず、サーバーの起動には毎回時間がかかる。モデルがキャッシュ済みでも、サーバーを起動する必要があったフックは開発機で 41.2 秒かかった（2026-11-22。サーバーが動いていない状態からの `--hook-submit`。次の呼び出しは 0.9 秒）。モデルがまだキャッシュにないときは、ダウンロードに 2〜10 分かかる。フックは最大 60 秒待ち、そのあとはサーバーなしで進める（上の「PID ファイルの扱い」）。これは仕様上の許容動作であり、その待ちはフックの `"timeout": 120`（§4「フックの制限時間」）に収まる。

### SQLite 剛性設定
接続時に以下を強制実行せよ:
```sql
PRAGMA synchronous = FULL;
PRAGMA journal_mode = WAL;
PRAGMA wal_autocheckpoint = 1000;
```

- `PRAGMA wal_autocheckpoint = 1000;` — WAL ファイルが 1000 ページ（約 4MB）を超えたら自動的にチェックポイント。長期稼働で WAL が肥大化することを防止。

### 即時物理保存（変更・最適化禁止）
`--buffer` または API経由の保存時、その瞬間に INSERT および COMMIT を完遂せよ。

**以下を絶対に行ってはならない（速度向上を理由とする場合も含む）:**
- 書き込みのバッファリング（`write_buffer`、`batch_insert`、遅延COMMIT等）
- 非同期書き込み（`asyncio`、スレッドキュー、バックグラウンドタスク等）
- トランザクションの一括化（複数INSERTを1トランザクションにまとめる処理）

> **補足: 即時物理保存の設計背景**
> すぐにコミットせずメモリ上に保持（バッファリング）した記録は、遅らせた書き込みの前にプロセスが強制終了されると消失する。保存の瞬間にコミットすれば、保存直後に強制終了されても何も失われない。速度よりDurabilityを最優先とする。これはパフォーマンス上の選択ではなく、設計上の不変条件である。

### 識別子

- **Owner ID**: 初回起動時に UUIDv4 を生成し `config.json` に保存。全レコードに刻印せよ。N3MC インスタンス間でデータをマージする際にデータ出所を保持するために使用する。
- **Local ID**: 初回起動時または `config.json` に未設定の場合、UUIDv4 を生成し固定保存する。N3MCインストール（またはエージェント）の識別子。全レコードに刻印せよ。マルチエージェント時は `/buffer` API の `local_id` パラメータでエージェント固有の UUIDv4 を指定可能（省略時は config.json の値を使用）。
  - **ユースケース**: 複数の Codex インスタンス（マシンやインストールごとに固有の `local_id`）、同一 N3MC DB を共有する異なるエージェント（Codex + CordX 等が各自のインスタンスで動作し固有の `local_id` を持つ）、エージェント種別やプロジェクト環境ごとの記憶分離。
  - **注意**: Free 版では `local_id` はレコードに記録されるが、ランキングには使用されない。同一環境の記憶を優先する `B_local` バイアス乗数は Pro 機能。
- **Session ID**: 1 つのタスク／プロジェクト／会話に属する記憶をまとめるためのグルーピングキー。**解決順**: (1) `/buffer`・`/search` API 呼び出しでの明示的な `session_id` 引数（最優先 — 既にセッションを管理しているホストが使う。例：n3memory-lite はタスク番号を割り当てる、Ollama 風のチャット切替 UI はチャット ID を渡せる）; (2) `N3MC_SESSION_ID` 環境変数（CLI の `--buffer` / `--search` は、呼び出したプロセスにこの値があれば (1) の `session_id` として送る。常駐サーバーはふつうフックが起動するので、サーバー自身の環境には利用者が CLI 側で設定した値がない。送らないと、利用者の値は効かない。2026-11-20）; (3) サーバー起動時に生成するプロセス単位の UUIDv4（ホスト由来のセッション ID を取得できない Codex 等のフォールバック）。全レコードに刻印するが、**`config.json` には永続化しない** — `session_id` は永続的なインストールではなく、一時的なタスク／プロジェクトを識別するためのもの。`b_session` ランキングバイアス（一致 1.0／不一致 0.6）を駆動し、現在のタスクの記憶を無関係な過去セッションより上位に浮上させる。

`config.json` の完全スキーマ（未設定項目は以下の規定値で自動初期化せよ）:

```json
{
  "owner_id":             "<UUIDv4 自動生成>",
  "local_id":             "<UUIDv4 自動生成>",
  "bind_host":            "127.0.0.1",
  "server_port":          18520,
  "embed_model":          "intfloat/multilingual-e5-base",
  "half_life_days":       90,
  "bm25_min_threshold":   0.1,
  "search_result_limit":  20,
  "min_score":            0.2,
  "search_query_max_chars": 2000,
  "vector_min_cos":       0.85,
  "relative_min_score_ratio": 0.6,
  "min_results":          3,
  "pair_top_n":           3,
  "pair_max_chars":       3000,
  "version_order_enabled": true,
  "version_sim_threshold": 0.98,
  "version_min_chars":    100,
  "reply_sim_rerank_enabled": false,
  "reply_sim_alpha":      0.3,
  "reply_sim_floor":      0.80,
  "reply_sim_span":       0.15
}
```

- `bind_host`: サーバーが待ち受けるアドレス。既定の `127.0.0.1` のまま使う（§3「常駐型 FastAPI サーバー」）。
- `search_result_limit`: `--search` が返す最大件数（1〜1365。§3.5「許される値」）。
- `min_score`: `--search` の結果から、`filter_score`（`time_decay` と `b_session` を掛けないスコア。§3「ランキング計算式」）がこの値未満のものを除外する（規定値 `0.2`）。`0.0` で無効化。
- `search_query_max_chars`: 検索クエリから使用する最大文字数（規定値 `2000`）。embedding モデル（512トークン）は約2,000文字以上を意味的に処理できません。増加させるとFTSクエリが遅くなる場合があります。
- `vector_min_cos`: ベクトル検索の候補にする cos 類似度の下限（規定値 `0.85`）。multilingual-e5 は無関係な記録どうしでも 0.80〜0.85 になるため、これ未満の候補を捨てる。**0.85 は `multilingual-e5-base` で測った値。** ほかの埋め込みモデルでは測り直すこと。目安は 0.80〜0.88（下げると拾いやすくなるが関係の薄い記録も混ざり、上げると差し込みは短くなるが関係のある記録も落ちやすい）。
- `relative_min_score_ratio`: `filter_score` が、最も高い `filter_score` のこの倍率未満の結果を捨てる（規定値 `0.6`、§5「検索結果の絞り込みと並べ替え」）。`0.0` で無効化。
- `min_results`（v1.6.0）: 下限を通った結果がこの件数に満たないとき、足りない分を**弱い候補**（下限で落ちた候補）で補い、別の見出しの下に出す（規定値 `3`、§5「検索結果の絞り込みと並べ替え」の手順 7）。`0` で補充しない。
- `pair_top_n` / `pair_max_chars`: Q-A の往復を差し込むのは上位 `pair_top_n` 件の往復だけ、合計 `pair_max_chars` 字まで（§5「Q-A ペアリング契約」）。
- `version_order_enabled` / `version_sim_threshold` / `version_min_chars`: 同じ内容の新しい版を上に並べる処理（§5）。`0.98` も `multilingual-e5-base` で測った値。
- `reply_sim_rerank_enabled` / `reply_sim_alpha` / `reply_sim_floor` / `reply_sim_span`（2026-11-17）: 返答との近さで並べ直す処理（§5「検索結果の絞り込みと並べ方」の 2b）。既定は off。`0.80` と `0.15` は `multilingual-e5-base` で測った値で、埋め込みのモデルを替えるとコサインの分布が変わるので、測り直す。
- v1.3.x の `dedup_threshold` と `context_char_limit` は**廃止**。既存の `config.json` に残っていても読まれない（消さなくてよい）。
- 値は引用符を付けずに書く（`"vector_min_cos": 0.83`）。型が違う値や許される範囲外の値は無視される（§3.5「許される値」）。
- `config.json` を書き換えると `code_version` が変わり、次のコマンドでサーバーが自動で起動し直して新しい値が効く。
- KNN の取得件数（K値）・`--repair` のバッチサイズ等の内部処理パラメータは実装者の判断に委ねる。ただし K 値は、許される `search_result_limit` のどの値でも、sqlite-vec の上限 4,096 以下にする（参照コードは `3 × search_result_limit`。§3.5「許される値」）。

> **複数アカウント運用時の注意**: 1台の PC で複数の Codex アカウントを運用し、同じ N3MC サーバー（同じ `server_port`・同じ DB パス）に接続する場合、各アカウントの `config.json` は個別に自動生成されるため `owner_id` / `local_id` が異なる。Free 版ではランキングに影響しないが、Pro 版にアップグレードすると他アカウントの記憶に `B_local=0.8` の減衰が適用される。全アカウントの記憶を同等に扱いたい場合は、1つ目のアカウントの `config.json` を他のアカウントにコピーして `owner_id` / `local_id` を統一すること。

> **チーム共有: 非対応。** CLI は常に `127.0.0.1:<server_port>` に接続する（リモートのサーバーアドレスを指定する設定はない）。サーバーには認証も暗号化もなく、`Host` ヘッダーがローカルでないリクエストと、`Origin` ヘッダー付きのリクエストは拒否する（§3「常駐型 FastAPI サーバー」）。`bind_host` は既定のままにすること。チームで 1 つの記憶 DB を共有するには別の設計が必要になる。

> **DB 変更（応用）**: 現仕様は SQLite + sqlite-vec を前提としているが、チーム規模が大きい場合は PostgreSQL + pgvector への移行も技術的に可能である。スキーマ互換性・接続プール・マイグレーション手順については Codex に相談すること。

- **主キー**: UUIDv7（時系列ソート可能。DB挿入時に生成）。外部ライブラリ `uuid7`（PyPI）を使用せよ。インポートは `from uuid_extensions import uuid7` で、ID は `str(uuid7())` とする（配布名は `uuid7` だがモジュール名は `uuid_extensions` なので、`import uuid7` は `ModuleNotFoundError` になる）。

### ランキング式

```
Final Score = (cos_sim × 0.7 + keyword_relevance × 0.3) × time_decay × b_session
```

**cos_sim（数学的正当性）**:

$$cos\_sim = \max(0,\ 1.0 - \frac{L2\_distance^2}{2})$$

- ベクトルがL2正規化済みのとき `L2_distance² = 2(1 - cosθ)` が成立し、上式は `cosθ` と等価。
- 負値（逆方向ベクトル）はランキングを破綻させるため `max(0, ...)` でクランプする。
- **前提**: `normalize_embeddings=True` を適用していない場合、この式は無効となる。

**keyword_relevance（FTS5 BM25の正規化）**:

SQLite FTS5 の `bm25()` は負値（より負 ＝ より関連度高）を返す。以下の手順で `[0.0, 1.0]` に正規化せよ：

1. 生スコアの絶対値が `bm25_min_threshold`（`config.json` の値、規定値 `0.1`）未満（ほぼ無関連）の場合は `keyword_relevance = 0.0` とする。
2. それ以外は結果セット内の最大絶対値で正規化する:

$$keyword\_relevance = \frac{-bm25\_score}{\max(1.0,\ \max_{results}(-bm25\_score))}$$

検索結果が0件の場合は `keyword_relevance = 0.0` とする。

**例外: 記録が 2 件以下の DB（2026-11-20）**: FTS5 は記録が 1〜2 件だと IDF を約 `1e-6` に丸めるため、本物の一致でも生スコアが約 `-2e-6` になり、手順 1 で 0 になってキーワードの一致が消える（埋め込みを使えないと検索結果が 0 件になる）。`memories` が 2 件以下のときだけ、手順 1 を行わず、`keyword_relevance = -bm25_score ÷ 最大の(-bm25_score)`（最良の一致が 1.0）とする。3 件以上の DB では上の式のまま。

2026-11-17 から、キーワード検索は 2 つの FTS5 の表（trigram と、下の CJK バイグラム）で行う。bm25 は**表ごとに、その表の**最大値で割る。両方で当たった記録は、高いほうの `keyword_relevance` を使う。

**FTS5 テーブル定義**: FTS5 仮想テーブルは必ず `tokenize='trigram'` を指定して作成せよ。**スタンドアロン形式（`content=` 句なし）の FTS5 を使うこと** — external-content 形式（`content='memories', content_rowid='rowid'`）は使ってはならない。external-content FTS5 は `delete_memory` および `--repair` のマイグレーションループで必要となる `DELETE FROM memories_fts WHERE rowid = ?` の自然な構文をサポートせず、代わりに `INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', ?, ?)` という特殊構文が必要。これを誤ると FTS インデックスが破損する（"database disk image is malformed" エラー）。スタンドアロン形式は `memories.rowid` と整合する rowid を持つプライベートな FTS シャドウを保持し、こちらが手動で揃える: `INSERT INTO memories(...)` の後 `cursor.lastrowid` を取得し、`INSERT INTO memories_fts(rowid, content) VALUES (?, ?)` に渡す。

```sql
-- memories テーブル（UUIDv7 が主キー、rowid は SQLite が暗黙で管理）
CREATE TABLE memories (
    id        TEXT PRIMARY KEY,  -- UUIDv7
    content   TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    owner_id  TEXT NOT NULL,
    local_id  TEXT,             -- N3MCインストール識別子（config.json より。マルチエージェント時はAPI経由で上書き可）
    agent_name  TEXT,             -- レコードを書いたAIエージェントの識別子（例：`"codex"`）。v1.1以前または指定なしの場合は NULL
    session_id  TEXT,             -- 会話／タスクのグルーピングキー（§3「識別子」）。b_session を駆動する
    turn_id     TEXT              -- 1 ターンの [user] 行と [claude] 行が共有する Q-A 往復のキー（§5「Q-A ペアリング契約」）
    -- SQLite は全テーブルに暗黙の INTEGER rowid を自動付与する
);
CREATE INDEX IF NOT EXISTS idx_memories_turn_id ON memories(turn_id);

-- FTS5 スタンドアロン — memories.rowid との整合は手動維持（trigram: 日本語対応の部分文字列マッチング）
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    tokenize='trigram'
);

-- CJK バイグラムの索引（2026-11-17）: bigram_text(content) を入れる。rowid は memories と同じ
CREATE VIRTUAL TABLE memories_fts_bi USING fts5(
    content,
    tokenize='unicode61'
);

-- sqlite-vec による KNN ベクトル検索（rowid で memories テーブルと紐付け）
CREATE VIRTUAL TABLE memories_vec USING vec0(
    embedding float[768]
);
-- INSERT 時: INSERT INTO memories_vec(rowid, embedding) VALUES (memories.rowid, serialize_vector(vec))
-- DELETE 時: DELETE FROM memories_fts WHERE rowid = <rowid>; DELETE FROM memories_fts_bi WHERE rowid = <rowid>; DELETE FROM memories_vec WHERE rowid = <rowid>;
-- ⚠️ memories を削除する際は、必ず memories_fts・memories_fts_bi・memories_vec も同一トランザクションで削除すること。
--    孤立レコードが残ると検索結果が壊れる。
```

**スキーママイグレーション（`migrate_schema`）**: 起動時に `PRAGMA table_info(memories)` を確認し、不足カラムを冪等に追加する:

```sql
ALTER TABLE memories ADD COLUMN local_id  TEXT;
ALTER TABLE memories ADD COLUMN agent_name  TEXT;
ALTER TABLE memories ADD COLUMN session_id  TEXT;
ALTER TABLE memories ADD COLUMN turn_id  TEXT;
CREATE INDEX IF NOT EXISTS idx_memories_turn_id ON memories(turn_id);  -- turn_id ができたあとで
```

`agent_name TEXT` — レコードを書いたAIエージェントの識別子（例：`"codex"`）。v1.1以前または指定なしの場合は `NULL`。

また、`migrate_schema()` は既存の `memories_fts` テーブルが `tokenize='porter unicode61'` で作成されている場合を検出し、`tokenize='trigram'` で自動的に再作成して全レコードを再インデックスする。この一度きりのマイグレーションにより、既存データベースも日本語検索精度の向上恩恵を受けられる。

> **補足: FTS5 トークナイザーの選定理由**
> `trigram` は日本語テキストに最適化された部分文字列マッチングのために採用している。日本語は単語間にスペースを持たないため、`porter unicode61` のような単語境界ベースのトークナイザーでは文全体が1トークンとして扱われ、FTS が実質的に無効化される。`trigram` は3文字単位の部分文字列インデックスを生成するため、形態素解析なしで日本語のキーワード検索が可能になる。英語のように空白で区切る言語でも動く。Free 版は PyPI でどこの国でも使われるため、既定はどの言語でも動くものにする（英語の語形変化 "running" → "run" はまとめないが、ベクトル検索で補える）。最終的なトークナイザーは、利用者が自分の言語・環境に合わせて直す（例: 英語中心なら `porter unicode61`、日本語の精度を上げるなら形態素解析）。README にもそう案内している。

**FTS5 制約**: `trigram` トークナイザーは **3 文字**単位（バイトではなく文字）でインデックスを作る。3 文字未満の語 — `AI`、`東京`、`龍馬` — は決して一致しない（FTS5 はその語に対して 0 行を返す）。そのため `_build_fts_query` は 3 文字未満の語を捨てる。語が 1 つも残らなければ trigram の検索を飛ばす（下のバイグラムの索引の検索は行う）。（v1.4.0 以前は単位を「3 バイト」と書いていたため、`東京` のような 2 文字の日本語の語が確認を通り、常に 0 行を返していた。）

**FTS 句読点除去（挿入側・検索側の両方で必須）**: 単語に隣接する句読点がトークナイゼーションの不一致を起こす可能性がある。**FTS5 への INSERT 時**および **FTS MATCH クエリ時**の両方で、同一の句読点除去関数を適用せよ:

```python
_FTS_PUNCT_RE = re.compile(r'[「」『』【】（）()\[\]{}<>〈〉《》・、。,.!！?？;；:：\-―─…\'\"\u201c\u201d\u2018\u2019]')

def strip_fts_punctuation(text: str) -> str:
    cleaned = _FTS_PUNCT_RE.sub('', text)
    return re.sub(r'\s+', ' ', cleaned).strip()

# INSERT 時: memories テーブルには原文、FTS には句読点除去済みテキストを登録
INSERT INTO memories_fts(rowid, content) VALUES (?, strip_fts_punctuation(content))

# MATCH 時（2026-11-17）: 制御文字と句読点を空白に → 空白で分割。CJK を含む
# 4 文字以上の語は 3 文字ずつ重ねて分け、ひらがなだけの 3 文字は捨てる。ほかの
# 3 文字以上の語はそのまま。3 文字未満の語は捨てる。重複を除き、最大 40 語、
# 各語を "..." で囲み（" は "" にする）、OR でつなぐ。
_FTS_MAX_TERMS = 40  # 大量テキスト入力時の FTS5 フリーズを防止
_FTS_CTRL_RE = re.compile(r'[\x00-\x1f\x7f]')
_CJK_CHAR_RE = re.compile(r'[぀-ヿ㐀-鿿豈-﫿가-힯]')
_HIRAGANA_ONLY_RE = re.compile(r'^[぀-ゟー]+$')

def _build_fts_query(query: str) -> str:
    terms, seen = [], set()
    for word in _FTS_PUNCT_RE.sub(' ', _FTS_CTRL_RE.sub(' ', query or '')).split():
        if len(word) > 3 and _CJK_CHAR_RE.search(word):
            grams = [word[i:i + 3] for i in range(len(word) - 2)]
            grams = [g for g in grams if not _HIRAGANA_ONLY_RE.match(g)]
        elif len(word) >= 3:
            grams = [word]
        else:
            grams = []
        for g in grams:
            if g not in seen:
                seen.add(g)
                terms.append(g)
    terms = terms[:_FTS_MAX_TERMS]
    if not terms:
        return ""                                  # → trigram の検索を飛ばす
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
```

- **INSERT 側は変えない**（`strip_fts_punctuation` は従来どおり句読点を取り除いて語をつなげたままにする）ので、FTS の登録し直しも新しいマイグレーションマーカーも要らない。句読点を空白にするのは検索側だけ。例: 保存された `架空の惑星「アルファ9」の気温設定` は `架空の惑星アルファ9の気温設定` としてインデックスされる。クエリ `「アルファ9」の気温は？` は語 `アルフ`、`ルファ`、`ファ9`、`の気温`、`気温は`（OR）になる。
- **OR にする理由（v1.5.0、Free v1.4.0 のレビューで見つかった）**: v1.4.0 は引用符で囲んだ語を AND（FTS5 の暗黙の演算子）でつないでいた。フックはユーザーのメッセージ全体をクエリにするので、`what is the quick fox doing in my DB` のような文は、`quick` と `fox` を含む記録があっても 0 行を返し、空白のない日本語の文は 1 つの長い語になって、その文そのものを含む記録にしか一致しなかった。そのため自動検索ではスコアのキーワード部分（30 %）がほとんど常に 0 だった。OR なら、どれか 1 つの語を含む記録が一致し、FTS5 の `bm25()` が、より多く・より珍しい語を含む記録を上位にする。3 文字未満の語は trigram では決して一致しないので捨てる。
- **CJK の語を 3 文字ずつに分ける理由（2026-11-17）**: それまでは、句読点のない日本語の文が 1 つの語になり、その文そのものを含む記録にしか一致しなかった。N3MC-Pro の本物の DB（2026-11-16、最近の質問 200 件）で、FTS が何か 1 件でも当たる質問は 33% だった。3 文字ずつに分けて OR でつなぐと 97% になり、共通する 3 文字が多く・珍しい記録を `bm25()` が上にする。ひらがなだけの 3 文字（`してく`、`ください`）はほとんどの記録に出るので捨てる。空白で区切る言語（英語）の質問は、これまでどおり語の OR になる。

**CJK バイグラムの索引（`memories_fts_bi`、2026-11-17）**: trigram の索引は 2 文字の語（`記憶`、`設定`、`PR`）を探せない。2 つ目のスタンドアロン FTS5 の表（`tokenize='unicode61'`）に `bigram_text(content)` を入れる。`strip_fts_punctuation` のあと、CJK の続きは 2 文字ずつ重ねて分け、それ以外はそのまま（`N3MCの設定` → `N3MC の設 設定`）。

- `insert_memory` が両方の表に書く。**消す道すべて**で、両方の表から消す（上の DELETE）。
- 質問の側（`build_bigram_query`）は、質問のバイグラムの語を引用符で囲んで OR でつなぐ。ひらがなだけの語は、ほかの語が残るなら捨てる。CJK でない 1 文字の語は捨てる。
- `hybrid_search` は、いつも両方の表（`search_fts` と `search_fts_bigram`）を探し、「keyword_relevance」に書いたとおりに合わせる。バイグラムの検索が失敗したら、trigram の結果だけで続ける。
- 表ができる前に保存された記録は、`--repair` が一度だけ索引する（`meta` 表のキー `fts_bigram`、§3.5。埋め込みを作らないので `max_records` で制限しない）。
- 理由（N3MC-Pro で測定、2026-11-16、ラベル付きの質問 138 問）: バイグラムの索引を外すと MRR が 0.046 下がった（95% 区間 −0.089〜−0.007）。

> **⚠️ 語の引用符囲みは必須（v1.4.0）**: 句読点除去のあとも `\ / # = @ * $ % + ^ ~ |` などの ASCII 記号や、単独の `AND` / `OR` / `NOT` / `NEAR` が残る。これをそのまま `MATCH` に渡すと FTS5 の文法エラー（`fts5: syntax error near "\"` 等）になり、`/search` が HTTP 500 を返して記憶の差し込みが「memory search unavailable」になる（実測で質問の約 12% で発生）。各語を FTS5 の文字列として `"..."` で囲めば、記号も演算子も文字どおりに照合される。（v1.5.0 からは引用符で囲んだ語を `OR` でつなぐ。語の間に書く `OR` は引用符の外にあるので演算子になり、語の中にあるユーザーの `OR` は文字どおりのまま。）
>
> **例外時も検索を続ける**: `hybrid_search` は `search_fts` の例外を捕まえ、キーワードの結果なし（ベクトル検索だけ）で続行する。FTS の失敗で検索全体を失敗させてはならない。

`--repair` 実行時に、既存 FTS レコードのうち句読点付きで登録されたものを検出し、句読点除去済みテキストで再登録せよ。この FTS クリーニングは**一度きりのマイグレーション**として実行し、完了後に `meta` 表のキー `fts_punct_cleaned` を書け（§3.5「索引の情報」）。キーが存在する場合はスキップし、毎セッション開始時の全件スキャンを回避すること。

**FTSのみヒットした場合のスコア**: ベクトル検索にはヒットせず FTS のみにヒットしたレコードは、`cos_sim = 0.0` として統合スコアを計算し、結果に含めよ。最終スコアは最大でも `0.3 × time_decay × b_session` だが、ランキング対象から除外してはならない。`min_score`（0.2）と相対足切りは `filter_score`（`time_decay` と `b_session` を**掛けない**スコア、下記）で判定するので、キーワードのみのヒット（`filter_score` は最大 0.3）は、`keyword_relevance` が 0.67 以上なら、どれほど古くても、どのセッションの記録でも残る。

**ベクトル検索の owner_id フィルタ**: `search_vector` は単一ユーザー前提のシステムであるため、`owner_id` によるフィルタリングを行わない。KNN 検索は全レコードを対象とする（これは仕様上の設計判断であり、複数ユーザー対応時は要改修）。

**絞り込み付きのベクトル検索（`--since` / `--until`）**: vec0 の KNN（`k = ?`）は全体から近い k 件を先に選ぶため、そのあとで時間範囲を絞ると、範囲内の記録がほとんど残らない。絞り込みがあるときは、**絞り込んだ rowid だけを対象に KNN を行う**こと。2 段階で行う:

```sql
-- 1) memories_vec で rowid と距離を得る
SELECT rowid, distance FROM memories_vec
 WHERE embedding MATCH :vec AND k = :k
   AND rowid IN (SELECT rowid FROM memories WHERE timestamp >= :since AND timestamp <= :until)
-- 2) その rowid で memories を引く
```

- `rowid IN (サブクエリ)` 付きの KNN は sqlite-vec v0.1.7 で確認済み。これが `sqlite3.OperationalError` になった場合（古い sqlite-vec 等）は、絞り込んだ行を `vec_distance_l2(embedding, :vec)` で全件計算して距離順に並べる方法（`_search_vector_exact`）に切り替える。
- 絞り込みがないときは従来どおり `search_vector`（全体の KNN）を使う。

**time_decay（半減期 `half_life_days` 日）**:

$$time\_decay = 2^{-\frac{days\_elapsed}{half\_life\_days}}$$

`days_elapsed` はレコード作成日時からの経過日数（浮動小数点）。`half_life_days` は `config.json` の値を使用する（規定値 90）。

`time_decay` は**並び順にだけ使う**（v1.6.0）。`score` には入るが `filter_score` には入らない。古い記録は、同じ関連度の新しい記録より下に並ぶが、古いことを理由に落ちることはない（下の表）。

**バイアス係数（Free 版）**:

| バイアス | 条件 | 係数（固定値） |
| :--- | :--- | :---: |
| **$b_{session}$** | 現在の `session_id` と一致 | **1.0** |
| | 不一致または NULL | **0.6** |

- `b_session` は Free 版で**唯一の**バイアス乗数。同一タスク／プロジェクト／会話に属する記憶をまとめて浮上させ、無関係な過去セッションの記憶を後ろに下げる。`0.6` という強めの不一致ペナルティにより、類似度・新鮮度に次ぐ Free 版の主要ランキングシグナルとして機能する。
- バイアス係数は設定ファイルによる変更不可（固定値）。
- `b_session` は、ベクトルと FTS の候補をまとめるのと同じループの中で Python で計算する（2 つの結果は Python でまとめるので、SQL の式にしても役に立たない）。

**`time_decay` と `b_session` は並べるためのもので、絞り込みには使わない（`b_session` は v1.5.0、`time_decay` は v1.6.0 から）**: 各候補は 2 つの値を持つ:

| 値 | 式 | 使い道 |
|---|---|---|
| `score` | `filter_score × time_decay × b_session` = `(cos_sim × 0.7 + keyword_relevance × 0.3) × time_decay × b_session` | 結果の並び順（と表示する `score=`） |
| `filter_score` | `cos_sim × 0.7 + keyword_relevance × 0.3`（`time_decay` も `b_session` も掛けない） | `min_score` と相対足切り（§5「検索結果の絞り込みと並べ替え」の手順 2 と 4）、弱い候補の並び順（手順 7） |

> **⚠️ 理由（v1.5.0、Free v1.4.0 のレビューで見つかった）**: v1.4.0 では 2 つの下限とも最終スコアと比べていたため、`b_session`（0.6）と相対足切り（0.6）が掛け合わさっていた。現在のセッションにベクトルのヒットが 1 件（cos ≥ 0.85、score ≥ 0.6）あるだけで、別セッションの記録が残るには `cos × time_decay ≥` 1 位の cos が必要になった。半減期 90 日では、**約 21 日より古い別セッションの記録は、内容が完全に一致していてもすべて落ちた**（再現: 現在のセッションの cos 0.86 の記録は残り、30 日前の別セッションの cos 0.99 の記録は 0.33 になって足切り 0.602 × 0.6 = 0.361 を下回った）。別セッションのキーワードのみのヒット（最大 0.18）は常に `min_score` 0.2 を下回り、手動の `--search` はすべての記録を別セッションとして扱うので、キーワードのみのヒットを一度も出さなかった。現在のセッションの記録はすでに Codex のコンテキストにある。それ以外をすべて切ってしまうと、セッションをまたぐ記憶の意味がなくなる。

> **⚠️ `time_decay` も `filter_score` から外した理由（v1.6.0、v1.5.0 の採点で見つかった）**: v1.5.0 は `filter_score` にまだ `time_decay` を掛けて `min_score`（0.2）と比べていた。半減期 90 日では、**DB にその 1 件しかなくても**、cos 0.86 の記録は約 150 日、cos 0.95 の記録は約 180 日で返らなくなった。記録は DB にも `--list` にも残るが、検索では引けない。実モデルでの測定（記録 50 件、質問 26 問）では、すべての記録を 1 年古くすると recall@3 が 23/26 から **0/26** になった。§1 は「一生の資産」としているので、古さで順位は下げてよいが、隠してはならない。`filter_score` から `time_decay` を外すと、1 年古くしたセットでも 23/26 に戻り、件数もノイズも変わらなかった。

- `b_local`（エージェント／インストール粒度の分離）は Free 版では **適用しない** — 全レコードが一致／不一致に関わらず `b_local = 1.0` として扱われる。エージェント／インストール単位で記憶を分離する `B_local` 乗数は **Pro 機能**であり、Pro 版では一致時 `b_local = 1.0`、不一致時 `b_local = 0.8` を適用する。

### Clean CLI
モデルロード警告等を CLI の stdout（Codex のコンテキストになる）に出さないこと。`n3memory.py` 内で FastAPI サーバーを subprocess 起動する際、以下のようにストリームをリダイレクトすること（呼び出し側に依存しない）:

```python
import os, subprocess, sys
log = open(SERVER_LOG, "ab")          # .memory/server.log。1 MB を超えていたら先に切り詰める
kwargs = {}
if os.name == "nt":
    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
else:
    kwargs["start_new_session"] = True
proc = subprocess.Popen(
    [*python_cmd(), '-m', 'n3memorycore.n3memory', '--run-server'],   # python_cmd(): 下の「安全なインポートパス」
    stderr=log, stdout=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **kwargs,
)
```

- stderr は `DEVNULL` ではなく `.memory/server.log` に送る（v1.5.0）。起動に失敗したサーバーが理由を残せるようにするため（§3「サーバーの起動」）。
- 切り離しのフラグにより、サーバーを起動したフックのプロセスが終わってもサーバーは動き続ける。

- `-m n3memorycore.n3memory` 形式が必須。これによりパッケージの相対インポートが解決される。サーバーを絶対ファイルパスで起動してはならない。
- 呼び出し側（settings.json の hooks 等）でリダイレクトを付与する必要はない。

**安全なインポートパス（2026-11-21）**: `python -m <モジュール>` は、今のフォルダを `sys.path` の先頭に置く。フックと §4 のコマンドは、利用者が Codex で開いているフォルダで動く。下の 2 つの決まりがないと、そのフォルダにある、N3MC が import するモジュールと同じ名前のファイル（たとえば、利用者がクローンしたばかりのリポジトリの中の `shlex.py` や `fastapi.py`）が import され、N3MC の中で動く。

**決まり 1 — 入口のモジュールは、今のフォルダを外す。** パッケージの中で、プログラムの入口になりうるモジュール（`if __name__ == "__main__":` で終わるもの。ここでは `n3memory.py`、`n3mc_hook.py`、`n3mc_stop_hook.py`）は、次のブロックを**最初の文**として持つ。docstring の直後、ほかのどの import よりも前に置く（フックのモジュールでは、UTF-8 のブロックをこのあとに置く）。

```python
import os as _os
import sys as _sys

if __name__ == "__main__":
    # Safe import path. Started as `python -m <package>.<module>`, Python has put the current folder
    # first on sys.path, so a file there named like a module imported below would run inside this
    # program. Drop that entry, unless this package itself lives in the current folder (a source
    # checkout run in place). Nothing else may be imported before this block.
    try:
        _cwd = _os.path.normcase(_os.path.abspath(_os.getcwd()))
        _pkg_parent = _os.path.normcase(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        if _sys.path and _os.path.normcase(_os.path.abspath(_sys.path[0])) == _cwd and _pkg_parent != _cwd:
            del _sys.path[0]
    except Exception:  # noqa: BLE001
        pass
```

- モジュールがプログラムとして動いたとき（`python -m …`）だけ働く。コンソールスクリプトやテストから import されたときは、何もしない。ライブラリは、自分を import したプログラムの `sys.path` を変えてはならない。
- ブロックが動く時点で、`os` と `sys` は読み込み済みである。import しても、ファイルを読まない。
- パッケージ自身が今のフォルダにあるとき（インストールせずに、ソースのフォルダでそのまま動かすとき）は、外さない。外すと、パッケージが見つからなくなる。

**決まり 2 — 子プロセスは `python_cmd()` で起動する。** `paths.py` に次の関数を置く。

```python
def python_cmd():
    """The command that starts a child Python: [sys.executable], plus -P on Python 3.11 and later so
    that the child does not put the current folder on sys.path (see the safe-path block at the top of
    the entry modules). -P is left out when this package itself lives in the current folder (a source
    checkout run in place), because the child could then not find the package."""
    import sys
    cmd = [sys.executable]
    try:
        cwd = os.path.normcase(os.path.abspath(os.getcwd()))
        pkg_parent = os.path.normcase(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if sys.version_info >= (3, 11) and pkg_parent != cwd:
            cmd.append("-P")
    except Exception:  # noqa: BLE001
        pass
    return cmd
```

子の Python のプロセス（上のコードのサーバーと、フックのモジュールからの呼び出し）は、すべて `[*python_cmd(), '-m', …]` で起動する。`[sys.executable, '-m', …]` で起動してはならない。`-P`（Python 3.11 から）は、今のフォルダを `sys.path` に足すこと自体をやめさせる。今のフォルダに、このパッケージと同じ名前のフォルダがある場合にも効く。

**この決まりで防げないもの**: 今のフォルダにある、このパッケージ自身と同じ名前（`n3memorycore`）のフォルダやファイル。そのフォルダで `python -m …` と打ってプログラムに入るとき（§4 のコマンドと、`python -m` の形で登録されたフック）は、もう一方のパッケージが import されるので、ブロックに届かない。Python 3.10 では、子プロセスも同じである（`-P` がない）。そのフォルダに置かれた `runpy.py` も動く。コンソールスクリプトから入るか、Python 3.11 以降で `python -P -m …` を使えば、起きない。（2026-11-21 に確認: 今のフォルダに `shlex.py` を置くと、この決まりの前は `python -m n3memorycore.n3memory` がそのファイルを動かし、決まりを入れたあとは動かさない。そこに `n3memorycore/` というフォルダがあれば、今も動く。）

**文字コード（UTF-8）**: `n3memorycore/n3memory.py` の `main()` 先頭、**および `n3memorycore/n3mc_hook.py` と `n3memorycore/n3mc_stop_hook.py` のモジュール先頭**（`sys.stdin.read()` や `subprocess.run` の呼び出しより前）で以下を実行し、Windows cp932 環境での文字化けをプログラム内部で解決せよ。

```python
for _stream_name in ("stdin", "stdout", "stderr"):
    _s = getattr(sys, _stream_name, None)
    if _s is not None and hasattr(_s, 'reconfigure'):
        try:
            _s.reconfigure(encoding='utf-8')
        except Exception:
            pass
```

- この処理により、呼び出し側が `python -X utf8` を指定する必要はない。
- `reconfigure` は Python 3.7 以降で利用可能。それ以前の環境は `PYTHONUTF8=1` 環境変数を代替手段とする。
- 多言語テキスト（日本語・英語・中国語 等）はすべて UTF-8 で統一する。
- ⚠️ **stdin を読む／stdin を subprocess にパイプするすべての Python エントリポイントで reconfigure ブロックが必須** — `n3memorycore/n3memory.py`、`n3memorycore/n3mc_hook.py`、`n3memorycore/n3mc_stop_hook.py` のいずれか一つでも忘れると、Windows で非 ASCII 入力（日本語、em-dash 等）が静かに mojibake し、その破損バイト列が `audit.log` と DB に永続化されて復元不能になる。フックスクリプトでは `main()` 内ではなく**モジュール先頭**に置くこと（最初の `sys.stdin.read()` より前に走らせるため）。

**パスのポータビリティ**: Pythonコード内のファイルパス構築はすべて `os.path.join()` または `pathlib.Path` を使用すること。パス区切り文字（`\` や `/` の文字列リテラルによるパス構築）の直接使用は禁止する。本システムはコード変更なしに Windows・Linux で動作しなければならない。

```python
# 正：os.path.join を使用
import os
db_path = os.path.join(base_dir, "data", "memory.db")

# 正：pathlib.Path を使用
from pathlib import Path
db_path = Path(base_dir) / "data" / "memory.db"

# 禁止：区切り文字のハードコード
db_path = base_dir + "/data/memory.db"   # NG
db_path = base_dir + "\\data\\memory.db" # NG
```


- 対応プラットフォームは **Windows と Linux**（Windows 11 と Ubuntu で確認）。macOS は対象外（v1.5.0。以前の版は対象に挙げていた）。どちらの OS でこの指示書からコードを再生成しても、コード変更なしに動作する実装が得られなければならない。

---

## 3.5. 耐障害性・エラーハンドリング

### config.json 破損時の自動復旧

`config.json` はユーザーが手で書き換える（`vector_min_cos` の調整など）ので、書き間違いを前提に扱う。**書き間違えた `config.json` を上書きしてはならない**（以前の実装は、読めないと既定値で上書きし、ユーザーが変えたポートなどの設定を消していた）。

| 場合 | 動作 |
|---|---|
| ファイルがない | 既定値に新しい `owner_id`・`local_id` を入れて保存する。**ファイルは排他的に作成する**（下記「config.json の書き込み」） |
| JSON として読めない、または一番外がオブジェクトでない | **`config.json` は書き換えない。** その間は既定値で動く。`owner_id`・`local_id` は DB から復旧し（下記）、DB にもなければ**その回だけ**の新しい UUID を使う（保存しない）。知らせ `config_unreadable` を出す |
| 値の型が既定値と違う（例 `"vector_min_cos": "0.83"` — 引用符付きの数値）、または値が許される範囲の外（下の表） | **その項目だけ**無視して既定値を使い、ほかの項目は使う。`config.json` は書き換えない。知らせ `config_type` に項目名を出す |
| 正しく読める | ID や既定のキーが足りなければ足して保存する。`config_unreadable`・`config_type` の知らせを消す |

- 型の確認（`_config_value_ok(key, value)`）: 既定値が真偽値なら真偽値だけ、文字列なら文字列だけを受け付ける。数値は下の表に従う（真偽値は数値として扱わない）。既定値が `None` の項目（`owner_id`・`local_id`）と、既定値にない項目は確かめない。

**許される値（v1.5.0）**:

| キー | 型 | 許される範囲 |
|---|---|---|
| `server_port` | 整数 | 1〜65535 |
| `search_result_limit` | 整数 | 1〜1365 |
| `pair_top_n`, `pair_max_chars`, `search_query_max_chars`, `version_min_chars` | 整数 | ≥ 1 |
| `min_results`（v1.6.0） | 整数 | ≥ 0 |
| `half_life_days` | 数値（int または float） | > 0 |
| `bm25_min_threshold` | 数値 | ≥ 0 |
| `min_score`, `vector_min_cos`, `relative_min_score_ratio`, `version_sim_threshold`, `reply_sim_alpha`, `reply_sim_floor` | 数値 | 0〜1 |
| `reply_sim_span` | 数値 | > 0 |

- 「整数」は JSON の整数（`2000`）のこと。`2000.0` のような float は、値が整数であっても**受け付けない**。これらのキーはスライスの境界や件数として使われる（`user_text[:search_query_max_chars]`）。v1.4.0 は `2000.0` を受け付け、そのあと `--hook-submit` はすべて検索の前に `TypeError` で失敗し、ユーザーのメッセージは DB に届かなかった（`audit.log` にしか残らなかった）。負の `server_port` や `half_life_days: 0` も v1.4.0 の確認を通っていた。
- 範囲外の値は型の違う値とまったく同じに扱う: そのキーだけ既定値を使い、知らせ `config_type` にそのキーを出す。
- **`search_result_limit` の上限が 1365 である理由（2026-11-18 の最終レビュー、C-06）**: 参照コードのベクトル検索は、sqlite-vec に `k = 3 × search_result_limit` 件の近傍を求める。sqlite-vec は 4,096 を超える `k` を断る。1366 以上では、ベクトル検索が毎回何も返さず（sqlite-vec の「k value in knn query too large」。ログに警告が出るだけ）、検索はキーワードの一致だけで続いていた。3 × 1365 = 4,095 が、動く最大の値である。

**`config.json` の書き込み（v1.5.0）**:

- ないファイルを**作る**ときは排他作成（`open(path, "x")`）を使う。`FileExistsError` で失敗したら、別のプロセスが先に作ったということなので、書かずにそのファイルを読む。これにより、新規インストールで 2 つのフックが同時に始まっても `owner_id` は 1 つになる（v1.4.0 では 2 つの違う値が書かれることがあり、レコードにその値が刻印されたあとで 2 つ目が 1 つ目を上書きしていた）。
- 既存のファイルを**更新する**とき（足りないキーを足すとき）は、同じフォルダに一時ファイルを書いて `os.replace` で元のファイルと置き換える。これで書き込みが途中で止まっても `config.json` が途中で切れたままになることはない。`notices.json` も同じ方法で書く。
- **既存のファイルに `owner_id` / `local_id` を補うとき（2026-11-22、レビュー #2）** は、プロセスの間で順番にする：ロックファイル `.memory/config.lock` を排他作成で取り（0.05 秒ごとに最大 10 秒やり直す。10 秒より古いロックファイルは残骸とみなして消す）、ロックの中で `config.json` を読み直し、まだ欠けているものだけを足し、`os.replace` で書き、ロックを消す。どのプロセスも、ロックの中でディスクに見つけた（または書いた）ID を使う。10 秒以内にロックを取れないとき（または作れないとき）は、これまでどおりロックなしで補う。（それまでは、ID のない同じファイルを読んだ 2 つのプロセスが、DB に戻せる記録がないとき、それぞれ自分の `owner_id` を書き、負けたプロセスの記録はファイルにない ID を持った。）
- 知らせは §3「知らせ」の仕組み（stderr、`audit.log`、検索結果の先頭に 1 日 1 回）で出る。直すと次の読み込みで消える。
- **DB からの ID 復旧**: `owner_id` または `local_id` が得られない場合、既存の DB レコードから最頻出の値を使う（`SELECT owner_id FROM memories GROUP BY owner_id ORDER BY COUNT(*) DESC LIMIT 1`）。DB にもレコードがない場合のみ、新しい UUID を生成する。

> **補足: DB からの ID 復旧の設計背景**
> `owner_id`・`local_id` が静かに再生成されると、既存の全メモリのバイアス計算が狂う。DB からの復旧により、この無症状障害を防止する。

### DB 破損時の検出と復旧

サーバー起動時（`lifespan`）には `PRAGMA integrity_check` を 1 回だけ実行する。一方 `_buffer_direct` フォールバック経路では **`PRAGMA quick_check`** を実行する（`integrity_check` は全テーブル全行走査で大型 DB ではフォールバックの度に数秒〜数分を要し、HTTP 失敗ごとに走らせる経路としては不適切なため、軽量な `quick_check` を使う）。**`quick_check` は 1 プロセスにつき最大 1 回**（v1.5.0）: 結果をモジュール変数に覚えておく。別のフォルダのサーバーがポートを使っている間はすべてのチャンクが `_buffer_direct` を通り、v1.4.0 はチャンクごとに `quick_check` を実行していた。いずれも：

1. 結果が `ok` でない場合、DB を `n3memory.db.corrupt-<YYYYmmddHHMMSS>.bak`（ローカル時刻。その名前がすでにあれば `…-2.bak`、`…-3.bak`、…）として退避する。
2. `n3memory.db-wal` および `n3memory.db-shm` のサイドカーファイルは削除せず、同じ名前の形（`n3memory.db.corrupt-<YYYYmmddHHMMSS>.bak-wal`、`…-shm`）で一緒に**移動する**。新しい空 DB が古い WAL を読み込んではならない — 移動しておけば削除したときと同じくそれは防げる — うえ、WAL には最新の記録が入っていることがあり、バックアップの隣に名前をそろえて置いてあれば `sqlite3 <backup> ".recover"` でまだ読める（復旧の前に `<name>-wal` / `<name>-shm` に名前を戻す）。
3. 新しい空の DB を作成する。
4. stderr に警告メッセージを出力し（復旧手順を含む）、知らせ `db_corrupt`（"The memory DB failed its integrity check and was set aside as <path>. A new empty DB is in use. To recover records: sqlite3 <path> .recover | sqlite3 recovered.db"）を出す。この知らせは、ほかの知らせと同じく検索結果の先頭に出る（§3「知らせ」）。

> **⚠️ 理由（v1.5.0、Free v1.4.0 のレビューで見つかった）**: v1.4.0 は固定の名前 `.corrupt.bak` を使っていたので、2 回目の破損で 1 回目のバックアップが上書きされた（Windows で確認）。また WAL と SHM のファイルを削除し、復旧に使えたはずの記録を捨てていた。知らせる手段は、フックでは表示されない stderr の 1 行だけだった。

**SQLite が例外を出す壊れ方（2026-11-18 の最終レビュー、F13）**：DB を開くとき（`get_connection` の中の `PRAGMA`）や確認そのものが `sqlite3.DatabaseError` — その下位の `OperationalError`（`database is locked` など）ではないもの — を出し、そのメッセージに `file is not a database` か `malformed`（`database disk image is malformed`）が含まれるときは、`ok` 以外の結果と同じに扱う：上の手順 1〜4（退避、新しい空の DB、通知）。2 つの確認を 1 つの関数で行う：`_connect_checked(pragma)` は `DB_PATH` を開き、`PRAGMA <pragma>`（起動時は `integrity_check`、`_buffer_direct` ではプロセスごとに 1 回 `quick_check`、そのあとはなし）を実行し、開いた接続を返す。`_is_corruption_error(e)` が上の判定である。`get_connection` は、失敗した `PRAGMA` を再送出する前に接続を閉じる（Windows でファイルを移せるように）。ほかの `DatabaseError` はそのまま再送出する。sqlite-vec の読み込みの失敗は、`Recovery: pip install sqlite-vec` を含む自分のメッセージのままにする。（それまでは「ok 以外の行を返す」確認だけを扱っていた。中身がごみのファイルは `file is not a database`、先頭のページが壊れたものは `database disk image is malformed` になり、退避も通知もなく、フックの保存は毎回 stderr だけの「Physical save failed」で失敗し、サーバーは起動しなかった。）

### マイグレーションのバッチ処理

`/repair` 内の一括マイグレーション（ベクトル再インデックス・FTS 句読点クリーニング）は **200 件ずつバッチ処理**で実行する。大規模 DB でのメモリ枯渇を防止するため、`fetchall()` ではなく `LIMIT 200` でフェッチする。**`OFFSET` は常に `0` に固定すること**——修復済みレコードは `WHERE mv.rowid IS NULL OR mf.rowid IS NULL` の結果セットから自動的に消えるため、`OFFSET` をバッチごとに加算すると残りの未修復レコードをスキップしてしまう（例：400 件未修復 → 200 件修復 → `OFFSET 200` で 0 件ヒット → 残り 200 件が永久に未修復になる）。各バッチで 1 件も修復できなかった場合（埋め込みモデル利用不可等）は無限ループを防ぐために即時終了する。

**埋め込みの間は書き込みのロックを持たない（2026-11-18 の最終レビュー、F11）**：ベクトルの修復は、バッチ全体の埋め込みを先に、トランザクションの外で計算し（開いているものは先にコミットする）、そのあとでバッチの `memories_vec` / `memories_fts` / `memories_fts_bi` の行を入れてコミットする — `--reembed` と同じ順序。（それまでは、最初の `INSERT … memories_vec` が書き込みのトランザクションを開き、バッチの残り — 最大 200 件 — を埋め込む間ずっと開いたままだった。その間に届いた `/buffer` は busy timeout まで待って `database is locked` で失敗し、`_buffer_direct` への切り替えも同じく失敗して、質問が保存されなかった。60 件と、1 件 0.25 秒の代役のモデルで再現した。）**書き込む前にもう一度確かめる（2026-11-20）**: 埋め込みのあと、`BEGIN IMMEDIATE` で書き込みのロックを取ってから、バッチの行ごとに、`memories` の行がまだあって同じ記録であること（`id` か `content` が同じ）、`memories_fts` / `memories_fts_bi` / `memories_vec` にその rowid の行がまだないことを確かめ、足りないものだけを書く。ほかの呼び出し（別のウィンドウのフック、手動の `--repair`）が埋め終えた行や、消された行は飛ばす。（それまでは、2 つの呼び出しが同じ未修復の行を読むと、あとの方が `UNIQUE constraint failed on memories_vec primary key` で止まった（2026-11-20、N3MC Pro の生成コードのレビューで再現）。）

**フックからの呼び出しごとの上限（v1.5.0）**: `/repair` は省略可能な本文 `{"max_records": int}` を受け付ける。`--hook-submit` は `{"max_records": 200}`（1 バッチ）を送る。これにより、大量の未処理分（例: 別のフォルダのサーバーがポートを使っていた間に `_buffer_direct` で保存された多数の記録）は、1 つの質問を何分も止めるのではなく、1 ターンに 1 バッチずつ片付けられる。`n3mc --repair` は上限を送らず、すべてを処理する。一回限りのマイグレーション（FTS 句読点クリーニング、ベクトル再インデックス）も同じ上限に従い、マーカーはマイグレーションが終わったときにだけ書く。

ただし **FTS 句読点クリーニング**は、処理した行も結果から消えない（UPDATE するだけ）ため、`OFFSET 0` では終わらない。こちらは `WHERE rowid > <前のバッチの最後の rowid> ORDER BY rowid LIMIT 200` のキーセット方式で進める。**続きから始める（2026-11-20）**: 終えた最後の rowid を `meta` のキー `fts_punct_cursor` に、各回の書き直しと同じトランザクションで書く。次の呼び出しは rowid 0 からではなく、その次から始める（`max_records` 付きの呼び出しが続いても、プロセスを起動し直しても進む）。最後まで読み終えたら `fts_punct_cleaned` を書き、`fts_punct_cursor` を消す。（それまでは、上限付きの呼び出しが毎回 rowid 0 から始まり、201 行目に届かず、マーカーも書かれなかった（2026-11-20、N3MC Pro の生成コードのレビューで再現）。）

### 索引の情報（`meta` 表）と `--reembed`（v1.8.0）

`n3memory.db` の索引がどう作られたかを示す情報は、**データベースの中**の、`init_db` が作る表に持つ：

```sql
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

| キー | 値 | 書くもの |
|---|---|---|
| `embed_model` | `memories_vec` のベクトルを作ったモデルの名前 | `/repair`（初回）と `--reembed` |
| `embed_dim` | `memories_vec` の次元。表そのものから読む（`init_db` が作った表なら `768`） | 同上 |
| `embed_model_at` | `embed_model` を書いた時刻（UTC の ISO 8601） | 同上 |
| `fts_punct_cleaned` | FTS の句読点クリーニングが終わったら `1` | `/repair` |
| `fts_punct_cursor` | FTS の句読点クリーニングが終えた最後の rowid。終わったら消す（2026-11-20） | `/repair` |
| `fts_bigram` | 古い行の `memories_fts_bi` を埋め終わったら `1` | `/repair` |
| `reembed_model`、`reembed_cursor` | 終わっていない `--reembed` の進み具合 | `--reembed`（終わったら消す） |

- **`/repair`** は、一度きりの処理（FTS の句読点クリーニング、バイグラムの埋め込み）を、そのキーが**データベースの中に**ないときに行い、処理が終わったときだけキーを書く。どちらも何度行っても結果は同じなので、すでに済んだデータベースでもう一度行っても、1 回の走査で済む。
- **`memories_vec` の次元（2026-11-22、レビュー #3）**：いつも表そのものから読む。`SELECT sql FROM sqlite_master WHERE name = 'memories_vec'` の `float[N]` の数で、定数 `EMBED_DIM` は使わない。`/repair` は、欠けた `meta` の行を補うときにこの値を `embed_dim` に書き、`--reembed`（下の手順 2）は試しのベクトルをこの値と比べる。（それまではどちらも 768 を使っていた。§3「埋め込み」の手作業の手順で 384 次元の表にしたあと、`--reembed` は `memories_vec has 768` と出して終了ステータス 1 で終わり、ベクトルの索引を作り直せなかった。）
- **`embed_model` がないとき**：`memories_vec` に行がなければ、設定の `embed_model`。そうでなければ、`.memory/vec_model.txt` があって空でなければその内容（v1.7.0 以前の印）。それもなければ、設定の `embed_model`。このファイルはこのためだけに読み、書き込みも削除もしない。
- **モデルの食い違い**：`meta.embed_model` が設定の `embed_model` と違うとき、`/repair` は通知 `embed_model_mismatch` を出す（§3「通知」）：`The stored vectors were made with <recorded>, but config.json sets embed_model to <configured>. Search quality is degraded until they are re-made: run n3mc --reembed (it re-embeds all <N> records with <configured>), or set embed_model back to <recorded>.` 一致すれば通知を消す。
- **`n3mc --reembed`** は、すべての記録を設定の `embed_model` で埋め込み直す。**CLI のプロセスの中で**行う（数分かかることがあり、HTTP の呼び出しでは時間切れになる）：
  1. このフォルダーのサーバーを止める（古いサーバーと同じ `/shutdown` の要求、§3「サーバーの起動」）。次の CLI の呼び出しで、設定のモデルで起動し直される。ほかのフォルダーのサーバーには触れない。
  2. 設定のモデルを読み込み、試しの文を 1 つ埋め込む。その次元が `memories_vec` の次元（上のとおり表から読む）と違えば、`N3MC: --reembed: <model> makes <d>-dimensional vectors but memories_vec has <D>; a different dimension needs the manual procedure in §3 "Embeddings".` を出し、何も変えずに終了コード 1 で終わる。
  3. 再開の位置：`meta.reembed_model` が設定のモデルと同じなら、`meta.reembed_cursor`（`memories.rowid`）の次から始める。違えば最初から始め、`reembed_model` を書く。
  4. `rowid` の順に 200 行ずつ：その行を埋め込み（`"passage: " + content`、正規化）、1 つのトランザクションで、その行を `memories_vec` から消し、新しいベクトルを入れ、`reembed_cursor` を最後の rowid にする。1 回ごとに stderr に `Re-embedded <done> / <total>` を出す。
  5. 行が残っていなければ：`embed_model`、`embed_dim`、`embed_model_at` を書き、`reembed_model` と `reembed_cursor` を消し、通知 `embed_model_mismatch` を消し、`Re-embedded <N> record(s) with <model>.` を出す。
  - 途中で止まっても（Ctrl+C、異常終了）、終わった回の分は残る。もう一度 `--reembed` を実行すれば、続きから行う。実行中に保存された行は、起動し直したサーバーが設定のモデルで埋め込む。
  - `--reembed` は自動許可の規則（§4）に入れない：人が実行するものである。

> **理由（v1.8.0、2026-11-17 の設計レビュー、提案 3）**：v1.7.0 までは、これらの情報をデータベースの隣の印のファイル（`vec_model.txt`、`fts_punct_cleaned`、`fts_bigram_v1`）に置いていた。しかしバックアップの手順で保存するのは `n3memory.db` と `config.json` だけである。同じ PC で古いバックアップを戻すと新しい印が残るので、バイグラムの埋め込みが行われず、古い記録の CJK のキーワード検索が当たらなくなった。別のモデルで作ったデータベースを新しい PC に移すと、設定のモデル名が新しい `vec_model.txt` に書かれ、食い違いが知らされなかった。警告も「`vec_model.txt` を消して `n3mc --repair` を実行する」と案内していたが、`--repair` は欠けたベクトルを足すだけなので、古いベクトルは残り、警告だけが消えた。

---

## 3.6. 取り出し拡張（Retrieval Extensions）

> **目的**: 保存済み記憶からの取り出しを強化する。すべて**追加機能**であり、既存スキーマ・既存 CLI・既存挙動には一切手を加えない。

### `--since` / `--until`（時間範囲フィルタ）

```bash
python -m n3memorycore.n3memory --search "キーワード" --since 2026-01-01 --until 2026-03-31
```

- `--search` および `--list` のオプションとして受け付ける。
- 既存の `timestamp` 列に対し `WHERE timestamp >= ? AND timestamp <= ?` を AND 結合する。新規スキーマ追加なし。
- **解釈（`_parse_time_bound`、v1.5.0）**: 日付（`2026-11-13`）、または日付と時刻の間が `T` か空白の ISO 8601 の日時（`2026-11-13T09:00`、`2026-11-13 09:00:00`）を受け付ける。オフセット（`+09:00`、`Z`）はあってもなくてもよい。日付だけの `since` は 00:00:00、日付だけの `until` は 23:59:59.999999 とする。
- **タイムゾーン**: オフセットのない値（日付だけの値はすべてこれ）は、そのマシンの**ローカルタイムゾーン** — 出力の `saved=` と同じ時計 — で読み、UTC に変換する。オフセットのある値は、そのオフセットのまま UTC に変換する。変換した境界は、保存されている `timestamp` の値（`insert_memory` が書く形式、UTC）とまったく同じ形式にそろえるので、SQL の文字列比較が正しくなる。
- **保存する `timestamp` の書式（2026-11-19、コードから書き起こした）**: すべての記録は `datetime.now(timezone.utc).isoformat()` で保存する。例: `2026-11-13T01:34:56.123456+00:00`（マイクロ秒つき、オフセットは `+00:00`。`Z` にはしない）。`--since` / `--until` の境界は `dt.astimezone(timezone.utc).isoformat()` で作る。SQL はこれらを文字列として比べるので、別の書式（`Z` で終わる、マイクロ秒がない）にすると、既存の DB の行との比較が狂う。保存された値にオフセットがなければ、`time_decay` は UTC として読む。読めない値では、`time_decay` は 1.0 になる。
- **読めない値**: 境界を解釈できない場合（`yesterday`、`2026-13-01`）は、stderr に 1 行（`--since: cannot read 'yesterday' (use 2026-11-13 or 2026-11-13T09:00)`）出し、検索せずに終了ステータス 2 で終わる。`since` が `until` より後のときも、`--since is later than --until` で同じようにする。
- 片方のみの指定（範囲を片開きにする）も可能。

> **⚠️ 理由（v1.5.0、Free v1.4.0 のレビューで見つかった）**: v1.4.0 は引数の文字列をそのまま DB の UTC のタイムスタンプと比べていた。日本では `--since 2026-11-13` が、13 日のローカル時刻 00:00〜08:59 に保存された記録（UTC では 12 日）を落としていた（`saved=` には 13 日と出ているのに）。`yesterday` はエラーにならず文字列として比べられ、`2026-01-01 10:00:00`（空白区切り）は `T` 区切りで保存された値との並びが正しくなかった。

### `--recall-thread`（会話再構成）

```bash
python -m n3memorycore.n3memory --recall-thread <turn_id> [--before N] [--after N]
```

- 指定 `turn_id` のターンと、それ以前 N 件・それ以後 N 件のターンを時系列で返す。
- `--before` / `--after` のデフォルトは各 2。
- 既存 `idx_memories_turn_id` インデックスを使用。新規インデックス不要。
- 既定の TSV は `--list` と同じ4列で件数行が付く。`--format jsonl` は 1 行 1 JSON で件数行を付けない。
- **どの行を出すか（2026-11-19、コードから書き起こした）**: 対象のターンの、最小の `rowid` と最大の `rowid` を取る。前の N ターンは、`MAX(rowid)` が対象の最小の rowid より小さい `turn_id`（NULL でなく、対象でもないもの）のうち、`MAX(rowid)` が大きいものから N 個である。後の N ターンは、`MIN(rowid)` が対象の最大の rowid より大きい `turn_id` のうち、`MIN(rowid)` が小さいものから N 個である。`turn_id` が NULL の行は、ターンとして数えない。選んだターンのすべての行を、`rowid` の順に出す。DB のファイルがないときは、stderr に `No DB found at <path>` を出す。
- **`--format jsonl` のキー**。`--list` は `id, content, timestamp, owner_id, local_id, agent_name, session_id, turn_id, role, source, state, replacement_turn_id`。`--recall-thread` は `id, timestamp, agent_name, turn_id, content`。
- 前後の候補は対象と同じ `session_id` で、対象ターンの範囲と重ならないものに限る。
- **運用**: Codex は `--search` のスニペットで文脈が足りない場合、ヒットの `turn_id` を `--recall-thread` に渡して周辺会話を取得できる。

---

## 3.7. 後方互換性（厳守）

本指示書のいかなる機能追加も、既存の `memories` / `memories_vec` / `memories_fts` スキーマおよび既存 CLI フラグの挙動を破壊してはならない。新機能は次のいずれかで実装すること：

- 新しい CLI フラグ・新しいサブコマンドの追加
- 新しい DB テーブル・新しいインデックスの追加（`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`）
- 既存テーブルへのカラム追加は `ALTER TABLE ... ADD COLUMN` のみ（`DROP` / `RENAME` は禁止）

既存ユーザの DB は、再生成なしにそのまま新仕様で動作すること。

---

## 3.8. CLI コマンドの入出力

公開入口は `n3mc`。インストール済みの Python では `python -I -m n3memorycore.n3memory` も使える。通常の会話は §4 のフックで保存する。

| コマンド | 入力・出力と動作 |
|---|---|
| `--help` | 引数なし。利用方法を標準出力へ。 |
| `--init` | データ先と設定の情報、フック登録結果を標準出力へ。不正なフック設定は保全し、終了コード 1。 |
| `--buffer [TEXT]` | 引数の本文を保存。省略または `-` は UTF-8 の標準入力を読む。`--agent-id NAME` と環境変数 `N3MC_SESSION_ID` を利用できる。通常の成功時は標準出力が空。 |
| `--search QUERY` | `--since` / `--until` に対応。`N3MC_SESSION_ID` を会話バイアスに使う。結果は Markdown の標準出力。 |
| `--repair` | 検索インデックスを修復し、変更件数を標準エラーへ。実行不能または失敗は終了コード 1。 |
| `--reembed` | `config.json` のモデルで再埋め込み。進捗と結果を標準エラーへ。失敗は終了コード 1。確定済みバッチの続きから再開できる。 |
| `--list` | `--since` / `--until` に対応。既定は4列の TSV と件数行。`--format jsonl` は1行1レコード。 |
| `--recall-thread TURN_ID` | 同じ会話の前後を出力。`--before` / `--after` の既定は各2。TSV と JSONL に対応。 |
| `--show-turn TURN_ID` | 指定ターンの全文をローカル時刻付きで標準出力に表示。 |
| `--stop` | 古い一時マーカーと監査ログの後処理。サーバー停止は §3 の `POST /shutdown` が担当する。 |
| `--run-server` | `config.json` を使いサーバーをフォアグラウンドで起動する。既定 `127.0.0.1:18520`。 |
| `--hook-submit` | 旧ホスト互換。標準入力の JSON から `prompt` または `message` を読み、検索結果を Markdown で返す。Codex は §4 の `n3mc-hook` を使う。 |
| `--save-claude-turn` | 旧ホスト互換。標準入力 JSON の `last_assistant_message` を保存。Codex は §4 の `n3mc-stop-hook` を使う。 |
| `--backup NEW_DIRECTORY` | 未作成の出力先にオンライン SQLite スナップショット、設定、ハッシュ付きマニフェストを作る。`path` と `records` を JSON で返す。 |
| `--restore-backup DIRECTORY --to-home NEW_DIRECTORY` | バックアップのハッシュと DB を検証して、未作成のデータ先に復元する。`path` と `records` を JSON で返す。 |
| `--export-records NEW_FILE` | 未作成のファイルに本文・来歴・履歴状態・索引メタデータを JSONL で書き、`path` を JSON で返す。 |
| `--forget-turn TURN_ID [--yes]` | 既定は対象件数のプレビュー。`--yes` は対象の本文・索引を削除し、同一ターンの再保存を防ぐ。結果は JSON。 |
| `--supersede-turn OLD --replacement-turn NEW [--yes]` | 既定はプレビュー。`--yes` は旧ターンを通常検索から外し、履歴を保持する。結果は JSON。 |

保全・履歴コマンドは、操作失敗時に標準エラーへ理由を出し、終了コード 1 を返す。使用方法の誤りは終了コード 2。

---

## 4. Codex フック

- `--init` は `$CODEX_HOME/hooks.json`（既定は `~/.codex/hooks.json`）に同期の `UserPromptSubmit` と `Stop` の command ハンドラーをマージする。テストでは `N3MC_CODEX_HOOKS_PATH` で変更できる。インストール済み Python の絶対パスをシェルに合わせて引用し、`-I -m n3memorycore.codex_entry --prompt` または `--stop` を指定する。Windows では通常の絶対パスを引用符なしで呼び出す。空白などを含むパスは PowerShell の呼び出し演算子で実行する。タイムアウトは 120 秒。サーバーの子プロセスにも分離モードを引き継ぐ。他のフックを保持し、既存ファイルをバックアップしてからアトミックに置換する。同一設定では書き換えない。読み取れない設定や不正な JSON はエラーにする。
- 標準入力から UTF-8 の JSON オブジェクトを読む。`session_id`（互換用に `thread_id` を許容）と `turn_id` は必須。両イベントは同じターンに同じ ID を使う。入力フックは `prompt`、Stop は `last_assistant_message` を読む。Codex アダプターはトランスクリプトを読まず、ターン ID を受け渡すファイルも作らない。
- 入力フックでは対象のループバックサーバーを確認し、最大 200 件のインデックス修復を試みる。応答待ちは修復が最大 3 秒、検索が最大 8 秒。既定で 2,000 文字までを検索クエリに使い、検索後に入力を保存する。サーバーが使えない場合も、自分の既存 SQLite を読み取り専用で開き、ローカル FTS で検索する。検索結果の Markdown は `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"..."}}` として返す。
- フックの保存要求の応答待ちは最大 8 秒。応答がない場合は SQLite に切り替え、同じフックの残りのチャンクも直接保存する。入力保存が失敗しても、検索結果を組み立てられていれば `additionalContext` を返し、`systemMessage` で保存失敗を伝える。Stop は応答を保存し、後処理を行う。返す内容がない成功時は標準出力を空にし、回復不能な失敗は終了コードで伝える。
- 保存しない依頼、システム入力、認証情報のパターンを検索・保存より前に確認する。保存対象外の入力は ID のハッシュでマークして Stop でもスキップする。認証情報を検知した応答も保存しない。生のフック入力をログに書かない。後処理で 30 日を超えたマーカーを消し、50 MB 超の監査ログをローテーションする。
- 動作指針は `AGENTS.md` に記載する。取り出した記録は過去のデータとして扱い、重要な事実は再確認する。手動で重複保存しない。Free はローカルフックだけを使い、N3MemoryCore MCP の登録や承認ポリシーの変更は行わない。

[Codex フックの設定と入力形式](https://learn.chatgpt.com/docs/hooks)


## 4.5. FastAPI エンドポイント仕様

CLI は FastAPI サーバーへ HTTP リクエストを送信する。全エンドポイントは `http://127.0.0.1:{server_port}` に対して発行する。

| メソッド | パス | 対応CLIコマンド | 説明 |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | （内部死活監視） | `{"status": "ok", "root", "code_version", "pid"}` を返す（§3「サーバーの名乗り」） |
| `POST` | `/buffer` | `--buffer`、フック | 本文 `{"content": str, "agent_name": str?, "local_id": str?, "session_id": str?, "turn_id": str?}`（`local_id` 省略時 → `config.json`、`session_id` 省略時 → サーバーのセッション。§3「識別子」。CLI は `N3MC_SESSION_ID` があれば送る）。保存する |
| `POST` | `/search` | `--search`、`--hook-submit` | 本文 `{"query": str, "session_id": str?, "since": str?, "until": str?}`。`since` / `until` は CLI と同じ規則で解釈する（§3.6）。読めない値には 400 を返す。結果を返す |
| `POST` | `/repair` | `--repair`、`--hook-submit` | 本文は省略可: `{"max_records": int?}`（§3.5「マイグレーションのバッチ処理」）。未インデックスレコードを修復 |
| `GET` | `/list` | （対応する CLI コマンドなし） | 全レコードの一覧を返す（各レコードに `agent_name` を含む）。API クライアントのために残している。`--list`・`--recall-thread`・`--show-turn` は DB を直接読み、これを呼ばない |
| `POST` | `/shutdown` | （内部、サーバーの入れ替え） | 本文 `{"root": str}`。`root` が自分の `root` と同じときだけ終了する。違えば 403（§3） |
| `DELETE` | `/delete/{id}` | — | **Pro のみ。** Free は常に 403（`{"detail": "Pro feature"}`）を返す |
| `POST` | `/gc` | — | **Pro のみ。** Free は 403 を返す |
| `POST` | `/import` | — | **Pro のみ。** Free は 403 を返す |

どのエンドポイントも、`Host` ヘッダーがローカルでないとき、またはリクエストに `Origin` ヘッダーがあるときは 403 を返す（§3「常駐型 FastAPI サーバー」）。

- `/buffer` の重複の扱い: **完全に同じ文だけ**を飛ばす（`check_exact_duplicate`）。`turn_id` があるときは**同じ `turn_id` の中だけ**で比べ、`turn_id` がないとき（手動の `--buffer`）は全体で比べる。完全一致を先に調べてから埋め込みを計算する。**類似度（cos_sim）による重複排除は行わない**（v1.4.0 で廃止。§5.4）。

### `--show-turn`（往復の全文）

```bash
python -m n3memorycore.n3memory --show-turn <turn_id>
```

- 指定した `turn_id` の全レコードを、Q-A ペアと同じ並び（[user] → [claude]、各ロール内は rowid 順）で、**content を切り詰めずに**出す。各レコードの前に `--- <id> saved=<ローカル時刻> ---` の行を置き、最後に `Total: N records`。
- 自分の DB を直接読む（サーバー不要）。
- 差し込みの Q-A の往復が `pair_max_chars` で切れたときの省略の行（§5）に、このコマンドが書かれる。

## 5. 検索結果の選び方

### Top-K のチャンク重複対策

1 つの長い Claude 応答が複数チャンクに分割されると、ハイブリッド検索で同一 `turn_id` の兄弟チャンクが Top-K を埋め尽くす病的ケースが発生する。これを防ぐため、`hybrid_search` の結果整形時に **同一 `turn_id` あたり最大 2 チャンクまで** とし、3 件目以降は Top-K リストから除外する（除外されたチャンクは `pairs`（Q-A 兄弟）セクションには出力される）。`turn_id` が NULL のレコード（手動 `--buffer` 等）はこの cap の対象外。

### 検索結果の絞り込みと並べ替え（v1.4.0。v1.5.0 から下限は `filter_score` で判定。v1.6.0 から弱い候補で補充）

`hybrid_search` はスコアを計算したあと、次の順で結果を整える。v1.3.x は `min_score`（0.2）だけで、無関係な記録も cos 類似度 0.80〜0.85 で候補に残り、差し込みが長く・関係の薄いものになっていた。

1. **ベクトル候補の下限**: cos_sim が `vector_min_cos`（0.85）未満のベクトル候補は捨てる（FTS にもヒットしていれば、`cos_sim = 0.0` の FTS のみヒットとして残る）。
2. **スコア計算と `min_score`**: `score` と `filter_score` を計算する（§3「バイアス係数」。v1.6.0 から `filter_score` には `time_decay` も `b_session` も掛けない）。**`filter_score`** が `min_score` 未満の結果を捨てる。残りを `score` の順に並べる。
   - **2b. 返答との近さで並べ直す（2026-11-17。`reply_sim_rerank_enabled` が true のときだけ。既定は false）**: `turn_id` のある結果ごとに、その往復の `[claude` の行の保存済みの埋め込みを平均し、質問の埋め込みとのコサインを取る。`score = (1 − α) × score ÷ 1 位の score + α × max(0, (コサイン − reply_sim_floor) ÷ reply_sim_span)`（α = `reply_sim_alpha`）として並べ直す。保存済みのベクトルだけを使い（モデルは呼ばない）、SQL は全往復で 1 回。エラーのとき、または質問を埋め込めなかったときは、結果を変えない。`filter_score` は変えない。理由: 往復の中でいちばん点の高い分割は質問のことが多く、言い回しが似ているだけの別の質問が 1 位を取っていた。N3MC-Pro（ラベル付きの質問 138 問）で α 0.3 にすると MRR が 0.029 上がった（95% 区間 +0.009〜+0.049）。伸びは主に 1 位。代わりに起きること: `score` が 0〜1 付近の目盛りになる。25 字以下の短い質問では、順位はほとんど動かない。
3. **同じ内容の版の並べ替え（`_order_versions_newest_first`、`version_order_enabled` が true のとき）**: 設定を作り直すと、古い版と新しい版の両方が出て、古い版が上に来ることがある。Q-A の差し込みは上から `pair_max_chars` まで入れるので、古い版しか入らないおそれがある。そこで:
   - 結果の各 turn_id について、その往復の「最初の `[claude` の行で、content が `version_min_chars`（100）字以上のもの」の埋め込み（`memories_vec` に保存済みのもの）を代表とする。代表のない往復・turn_id のない結果は対象外。
   - **別の turn_id どうし**で代表の cos 類似度が `version_sim_threshold`（0.98）以上なら同じ内容の版とみなし、グループにする（推移的に結ぶ）。
   - 各グループの中で、往復を新しい順（その往復の最初の行の `(timestamp, id)` の降順。`id` は UUIDv7 なので同じ秒でも順が決まる）に並べ直す。**結果の位置とその位置のスコアはそのまま残し**、その位置に入る行だけを入れ替える（新しい版がグループの最高スコアを受け継ぐ）。同じ往復の行どうしの順は変えない。
   - 並べ替えた行には `_version_group` の印を付ける。**記録は消さない。**
   - 0.98 の根拠（multilingual-e5-base で測定）: 同じ設定の新旧 1.0、形が同じで中身の違う設定 0.88〜0.91、1 つの返答の中の違う項目は最大 0.95。**質問の文だけでは比べない**（「X の設定を作成して」と「Y の設定を作成して」は 0.985 になるため）。
   - 限界: 書き出しだけ同じ往復も版とみなされうる。全文を書き直さない新版（代表の分割が変わらない）は検出しない。
4. **相対の足切り**: **`filter_score`** が、最も高い `filter_score` の `relative_min_score_ratio`（0.6）倍未満の結果を捨てる。ただし `_version_group` の印の付いた行は落とさない（古い版も残す）。手順 3 は位置の間で行を動かし、各位置は自分の `score` を保つ。`filter_score` も同じように位置とともに動く。
5. **完全に同じ content の集約（`_collapse_identical_content`）**: content が完全に同じ結果は、いちばん上の位置に 1 件だけ残し、その中身（id・timestamp・turn_id）は**新しい記録**のものにする。
6. **turn_id ごとの 2 件の上限**（上記「Top-K のチャンク重複対策」）と `search_result_limit`。
7. **弱い候補による最低件数の補充（v1.6.0）**: 手順 6 の後に残った結果が `min(min_results, search_result_limit)` 件に満たないとき、**この検索で取得したが手順 1・2・4 で落ちた候補**から、足りない分を足す。
   - 弱い候補になるのは、手順 1 の `vector_min_cos` で落ちたベクトル候補（**実際の `cos_sim` で計算する**。FTS のみヒットとしての `0.0` ではない）と、`min_score`（手順 2）・相対の足切り（手順 4）で落ちた結果。手順 1 で落ちて FTS にもヒットした記録は、実際の `cos_sim` と `keyword_relevance` を持つ 1 件の候補とする。`filter_score` が `1e-6` 未満（類似度もキーワードも寄与なし。float32 のベクトルの L2 → cos の変換では、直交するベクトルでも約 `1e-7` が残るので、ちょうど `0` とは比べない）の候補は足さない。`since` / `until` の範囲は普通の結果と同じく効く（弱い候補も同じ絞り込み済みの検索から来る）。
   - **`filter_score` の高い順**に取る（同じ値なら `(timestamp, id)` の新しいほうが先）。`score` は普通の結果と同じ式で計算して `score=` に表示するが、弱い候補の並び順には使わない。
   - 手順 5（同じ content の集約）と手順 6（turn_id ごとに 2 件まで）は、足す行にも、**すでに結果にある行と合わせて**当てる。content が結果の行と同じ候補や、その `turn_id` の行がすでに結果に 2 件ある候補は飛ばして次を見る。
   - 合計が `min(min_results, search_result_limit)` に達するか、候補がなくなったら止める。足した行にはすべて `_weak` の印を付ける（`/search` では `"weak": true`、§4.5）。弱い候補は常に普通の行のすべてより後に来る。
   - `min_results: 0` ではこの手順を行わない。空のクエリには候補がないので、何も返さない。
   - 弱い候補は、普通の結果の手順 3〜6 には関わらない（版の並べ替えで動かさず、相対の足切りの 1 位の値にも数えない）。
8. **Q-A の往復の選択**（`pair_top_n` / `pair_max_chars`、上記「Q-A ペアリング契約」）。`_weak` の付いていない行だけを見る。

> **注: 弱い候補を足す理由（v1.6.0、v1.5.0 の採点で見つかった）**: 下限は差し込む文脈を短く保つように決めてあるので、記憶がまったく入らないターンがあった。実モデルでの測定（記録 50 件、質問 26 問）では、1 問あたり平均 1.0 件で、26 問中 2 問は 0 件だった。弱い候補を 3 件まで補うと、recall@3 は 23/26 から 24/26 になり、1 問あたりおよそ 2 件の弱い候補が加わった。**欠点**: 毎ターン最大 3 件（チャンクは最大 400 字）が増え、その大半は関係の薄い記録で、無関係な質問でも必ず 3 件返る。Codex が読み飛ばせるように見出しを分け、大きな Q-A の往復のブロックが弱い記録で埋まらないように、往復の選択から外している。見出し、`min_results` の名前、指示の文面は N3MC Lite と共通にする。

---

## 6. 自律評価（[N3MC v1.9.1 Evidence Report]）
実装完了後、以下のテストを自律解決し、満点（⭐⭐⭐⭐⭐）を目標に結果を報告せよ。

> **実装完了の定義**: テスト 1〜6 を一時環境で自律実施 → `n3mc --init` で登録し、利用者がフックを信頼 → テスト 7〜10 を確認して Evidence Report に記録する。満点（⭐⭐⭐⭐⭐）を目標とし、未実施・不合格はそのまま示す。

1. **常駐速度 & プロセス管理**: `--search` の応答時間を計測し記録せよ（達成目標: CPU 環境で 2.0s 以内）。PIDファイルの生成・削除・再起動が正常に機能することを確認せよ。

2. **強制終了テスト（Durabilityの証明）**: データを1件 `--buffer` で保存直後にプロセスを強制終了（Ctrl+C）し、再起動後に `--list` でそのレコードがDBに残留していることを物理的に証明せよ。`--list` の出力フォーマットは以下の形式とする（1件1行、タブ区切り、4 カラム固定）:

   ```
   [UUIDv7]\t[timestamp]\t[agent_name]\t[content の先頭 80 文字]
   ```

   - カラム間はシングルタブ（`\t`）で連結。本仕様の旧版に見られた半角空白 4 つは表記上のものであり、リテラルではない。
   - 「content の先頭 80 文字」は `content[:80]` を意味する — **content 全体の先頭 80 文字**であり、「先頭行の 80 文字」ではない。その 80 文字内に改行（`\n`、`\r`）が含まれる場合は単一の半角スペースに置換し、タブ区切りレイアウトが 1 レコード = 1 行を保つようにすること。
   - `agent_name` が `NULL` の場合は `-` を出力する。
   - 末尾に総件数 `Total: N records` を出力すること。
   - コードレビュー時に `write_buffer`・`batch_insert`・非同期書き込み・遅延COMMITが存在しないことを静的に確認せよ。

3. **実在人物テスト（実在歴史データ）**: 実在の歴史人物に関するテキストを保存後、その人物名で `--search` を実行し、**検索結果の上位3件以内** に該当レコードが含まれることを合格基準とする。加えて、`--search` の結果が **stdout に出力されていること**（ターミナルに検索結果が表示されること）を確認せよ。stdout が空の場合は不合格とする。
   - 日本語版の例: 「坂本龍馬」
   - 英語版の例: 「Abraham Lincoln」

4. **架空設定テスト（創造的架空設定）**: 架空の設定（例: キャラクター名・世界観・固有名詞）を含むテキストを保存後、`--search` で取得し、**保存したテキストの全フィールドが一字一句変化なく復元できる**ことを合格基準とする。架空設定テキスト（非コード）は完全記録契約により一字一句保持される。Codex 応答中のコードブロックは文書設計に従い `[code omitted]` に置換される。
   - 日本語版の例: 「ソラニア（架空の浮遊都市）」
   - 英語版の例: 任意の架空のキャラクター・場所・固有名詞

5. **FTS 句読点耐性テスト**: 括弧・句読点を含むテキスト（例: `架空の惑星「アルファ9」の気温設定`）を `--buffer` で保存後、括弧を含まないクエリ（例: `アルファ9の気温`）で `--search` を実行し、**上位3件以内にヒット**することを合格基準とする。FTS5 trigram のインデックスに句読点除去が適用されていること、およびクエリ側でも同じ除去が行われていることの両方を検証するテストである。
   - 加えて、記号を含むクエリ（例: `C:\Users\test #tag = @a * $b % AND OR NOT "q"`）で `--search` を実行し、**エラーにならず**（stdout に `memory search unavailable` が出ない）結果が返ることを確認せよ（§3「語の引用符囲みは必須」）。

> テスト 6 の変更は試験用 DB だけで行う。以下のパスは `N3MC_HOME` が指す試験用の場所に置き換える。

6. **--repair FTS マイグレーションテスト**: `meta` 表の `fts_punct_cleaned` の行を消した状態で（`sqlite3 "/path/to/test-data/.memory/n3memory.db" "DELETE FROM meta WHERE key='fts_punct_cleaned'"`）`n3mc --repair` を実行し、以下を確認せよ:
   - FTS クリーニングが実行されること（句読点付きレコードがあれば件数が報告される）
   - `meta` 表の `fts_punct_cleaned` の行がまた書かれること
   - 再度 `n3mc --repair` を実行しても FTS クリーニングがスキップされること（キーにより全件スキャンが回避される）

7. **フック統合テスト**: Codex の実セッションで以下を確認せよ。
   1. **グローバルフック登録の存在確認**（必須ゲート、§4）。Free をインストールした Python 環境で次を実行する。
      ```sh
      python -c "import json; from pathlib import Path; from n3memorycore.codex_install import hooks_path, _owned; h=json.loads(Path(hooks_path()).read_bytes())['hooks']; expected=(('UserPromptSubmit','--prompt'),('Stop','--stop')); assert all(sum(_owned(item, flag) for group in h.get(event,[]) for item in group.get('hooks',[])) == 1 for event,flag in expected), 'N3MC Free hook missing or duplicated'; print('OK')"
      ```

      合格基準: `OK` が出力されること。Free のハンドラーを各 1 件検出する。登録後、Codex デスクトップ版では **設定 → Hooks**、CLI では `/hooks` から両フックの有効化と信頼を確認する。失敗した場合は、§4 の登録を確認してから進む。
   2. **UserPromptSubmit**: **n3mc-free-codex プロジェクトディレクトリの外**で新規チャットを開き、入力を送る。その入力が DB に保存され、以前の記録に一致する入力では `# Recalled Memory Context` が `hookSpecificOutput.additionalContext` に含まれることを確認する。プロジェクト外から試験することで、ユーザー全体の登録漏れを検出できる。
   3. **Stop**: 同じチャットで最終応答が表示されたあと、`n3mc --list --format jsonl` で `[user]` の入力と `[claude]` の応答が同じ `session_id`・`turn_id` で保存されることを確認する。応答の保存はターン終了時に行われる。

8. **stdout 出力テスト（memory_context.md を作らない）**: `--search` を実行し、結果が **stdout に出力される**こと、および `~/.n3mc/.memory/memory_context.md` が**作られない**ことを確認せよ。

9. **完全記録テスト（旧「ノイズフィルタテスト」の置き換え）**: 以下のフィルタが**廃止**されていること、および空でない入力がすべて記録されることを確認せよ。
    - Stop に 2 文字の応答を渡し、入力と同じ `session_id`・`turn_id` で保存されることを確認する（旧「3文字未満フィルタ」は存在しない）。
    - UserPromptSubmit に 5 文字の入力を送り、保存を確認する（旧「10文字未満フィルタ」は存在しない）。
    - 定型語（例: `ok`、`yes`、`thanks`）を `[user]` として渡し、**レコードが保存される**こと（旧 `_SKIP_PATTERNS` フィルタは存在しない）。
    - フック失敗時は利用者に失敗が伝わり、生の入力や応答が `audit.log` に記録されないことを確認する。
    - 形のそろった長い返答（例: 12 項目・約 2,000 字の設定。400 字ずつ分割される）を 1 つの往復として保存し、**分割がすべて DB に残る**こと。続けてほぼ同じ文の設定（一部の値だけ変えたもの）を別の往復として保存し、**1 つ目の分割が 1 件も消えず、2 つ目の分割もすべて残る**こと（類似度による重複排除の廃止）。

10. **全自動保存テスト（Fully Automatic Saving の検証）**: 以下の手順でフックによる全自動保存が正常に機能していることを確認せよ。
    1. テスト前の DB レコード件数を `--list` で記録する。
    2. Codex セッション内で **3ターン以上** の会話を行う（ユーザー発言 + Codex 回答の往復）。この間、Codex は `--buffer` を **一度も手動呼び出ししない**こと。
    3. `--list` で DB レコード件数を再確認し、ユーザー発言（`[user]` プレフィックス）と Codex 回答（`[claude]` プレフィックス）の **両方** が自動保存されていることを確認する。
    4. **合格基準**: **すべての**会話ターンについてユーザー発言・Codex 回答が各1件ずつ保存されている——短い文字列や定型応答でも一切スキップされない（完全記録契約）。Codex が `--buffer` を手動呼び出しした形跡がないこと。

### 6.1 フックを有効にして、3 ターンの自動保存を確認する

1. Codex デスクトップ版では **設定 → Hooks** を開きます。Codex CLI では `/hooks` を開きます。**N3MC Free memory** の `UserPromptSubmit` と `Stop` が登録され、両方が有効かつ信頼済みであることを確認します。一覧に出ない場合は §4 の登録先を確認します。
2. N3MemoryCore のソースフォルダとは別のフォルダで、ローカルの新しい Codex チャット **A** を開きます。次の入力を上から順に **1 通ずつ**送り、その都度、応答が最後まで表示されるのを待ちます。三つの入力をまとめて送ると 1 ターンになります。

   ```text
   保存テスト1。架空の浮遊都市ソラニアの合言葉は「琥珀のペンギンQ47」です。合言葉をそのまま一行で返してください。
   ```

   ```text
   保存テスト2。架空の探査船ミスト号の確認番号は「ミスト582」です。確認番号をそのまま一行で返してください。
   ```

   ```text
   保存テスト3。記録確認の印として「テスト完了R39」とだけ返してください。
   ```

3. N3MemoryCore Free を入れた Python 環境のターミナルで、次の確認コマンドを実行します。複数の版を使っている場合は Free の実行環境とデータ先を確認してください。Free の既定のデータ先は `~/.n3mc` です。

   ```sh
   n3mc --list --format jsonl
   ```

   Windows で `n3mc` が見つからず、Free をソースフォルダの `.venv` にインストールした場合は、そのフォルダから `.\.venv\Scripts\n3mc.exe --list --format jsonl` を実行できます。件数が多いときは、PowerShell で次のようにテストの行に絞れます。

   ```powershell
   n3mc --list --format jsonl | Select-String -SimpleMatch -Pattern '保存テスト1','琥珀のペンギンQ47','保存テスト2','ミスト582','保存テスト3','テスト完了R39'
   ```

   **合格条件**は、3 ターンそれぞれに `agent_name: codex` の入力 `[user]` と応答 `[claude]` が 1 件ずつあり、各組の `turn_id` が一致することです。3 組の `session_id` は同じで、`turn_id` はターンごとに異なります。`n3mc --show-turn TURN_ID` の `TURN_ID` を実際の値に置き換えると、その入力と応答をまとめて確認できます。テスト中は手動保存の `--buffer` を使わないでください。

### 6.2 別チャットからの取り出しと保存しない指定を確認する

1. チャット A とは別の作業フォルダで、新しい Codex チャット **B** を開きます。合言葉や番号の値を入力に含めず、次の質問を 1 通ずつ送ります。

   ```text
   前のチャットで登録した架空の浮遊都市ソラニアの合言葉は何ですか？ 見つからなければ「見つからない」と答えてください。
   ```

   ```text
   前のチャットで登録した架空の探査船ミスト号の確認番号は何ですか？ 見つからなければ「見つからない」と答えてください。
   ```

   **合格条件**は、各質問の応答にチャット A で指定した値が示されることです。フック出力を確認できる環境では、`# Recalled Memory Context` にチャット A の記録が含まれることも確認します。ほかの記憶フックも有効な場合は、Free のフック出力を確認するか、Free だけを有効にしたテスト用環境で確認します。
2. チャット B で次の入力を送り、応答が終わったあとで再度 `n3mc --list --format jsonl` を実行します。

   ```text
   このターンを保存しないでください。テスト用の印は「青いカメZ68」です。この印だけを返してください。
   ```

   **合格条件**は、この入力と応答のどちらにも該当する新規レコードがないことです。
3. 入力も応答も記録されない場合は、Hooks 画面で両フックの状態と実行エラーを確認し、ターミナルがフックと同じデータ先を参照しているかを確認します。入力だけがある場合は `Stop` を調べます。両方の記録があるのに取り出せない場合は、チャット B の `UserPromptSubmit` の出力を調べます。結果には「登録・信頼」「入力・応答の保存」「別チャットからの取り出し」「保存しない指定」を個別に記録します。

---

## 7. 自動テスト（pytest）

> **目的**: 手動 Evidence Report を補完する、反復実行可能な自動回帰テスト。プロジェクトルートから `python -m pytest tests/ -v` で実行。
>
> **前提**: `pip install pytest httpx`
>
> **Embedding モデル**: Embedding モデルを必要とするテスト（`test_processor.py::TestEmbedding`、`test_api.py`）は session スコープのフィクスチャでモデルを1回ロード（約5秒）。`test_api.py` のテストは、どれもモデルが要る。`client` フィクスチャが、最初のテストの前にモデルを読み込むからである。`-k "not TestEmbedding"` では、これを飛ばせない。ほかのテストは、モデルなしで動く（2026-11-17、空のモデルキャッシュと `HF_HUB_OFFLINE=1` で確認）。Layer 1 テストは決定論的なダミーベクトルを使用し、モデル依存を回避。

### ディレクトリ構成

テストはリポジトリルートの `tests/` 配下に置く（パッケージ内には**置かない**）。インポートはインストール済みの `n3memorycore` パッケージ経由で解決する（`sys.path` ハックは禁止）。

```
n3mc-free/
└── tests/
    ├── conftest.py          # 共通フィクスチャ：隔離DB、設定、ダミーベクトル
    ├── test_safe_path.py    # 安全なインポートパス: 今のフォルダのファイルが N3MC の中で動かない（モデル不要）
    ├── test_database.py     # Layer 1: DB単体テスト（CRUD、スキーマ、トランザクション）
    ├── test_dedup_concurrent.py # Layer 1: 同じターンの同じ文を同時に 2 回保存する（R04。モデル不要）
    ├── test_processor.py    # Layer 2: ランキング数学、purify `[code omitted]` 置換検証、Refresh
    ├── test_api.py          # Layer 3: FastAPIエンドポイントテスト（TestClient）
    ├── test_hooks.py        # Layer 4: フック統合（完全保存チャンク化、画像除去、監査ログ）
    ├── test_hooks_encoding.py # サロゲート除去・UTF-8 の回帰テスト
    ├── test_regressions.py  # Layer 5: v1.4.0〜v1.6.0 の修正の回帰テスト（モデル不要）
    ├── test_search_port_2026_11_17.py # Layer 5: 日本語の FTS、バイグラムの索引、システムの入力を飛ばす、返答との近さの並べ直し
    ├── test_review_2026_11_17.py      # Layer 5: チャンクの長さの上限、Windows のフックのパス（モデル不要）
    └── test_index_meta.py             # Layer 5: meta 表、モデルの食い違いの通知、--reembed（v1.8.0。モデル不要）
```

**本物のデータを守る（必須）**: `conftest.py` に autouse の fixture を置き、`n3memory` モジュールの `HOME_DIR`・`MEMORY_DIR`・`DB_PATH`・`PID_FILE`・`AUDIT_LOG`・`NOTICES_FILE`・`CONFIG_FILE`・`TURN_ID_FILE`・`SERVER_LOG` とサーバー起動のマーカー — **およびフックのモジュール**（`n3mc_hook`・`n3mc_stop_hook`）**の `AUDIT_LOG`** — を一時フォルダに向け、`--init` が使うユーザーの `~/.Codex/settings.json` を一時ファイルに向け（例: テストで `HOME` / `USERPROFILE` を設定する）、`_request_shutdown` と HTTP の送信（`_post`・`_get`）を本物のサーバーに届かない偽物に差し替えること。テストが本物の `~/.n3mc` の `notices.json`・`audit.log` に書いたり、本物のサーバー（18520）に `/shutdown` を送ったりしてはならない。

Codex 版では `N3MC_CODEX_HOOKS_PATH` を一時 `hooks.json` に向け、`codex_entry.MEMORY_DIR` も試験用に差し替える。以下の旧ホストのテスト名・件数は回帰項目の参照用。Codex の入口は `tests/test_codex_integration.py` で試験する。独立した `test_safe_path.py` がない場合は、登録コマンドを別フォルダから実行して安全なインポートを確認する。
 **HOME を差し替えると Hugging Face のキャッシュの場所も変わり、`TestEmbedding` などが埋め込みモデル（約 470 MB）をテストごとに一時フォルダへダウンロードし直す。** fixture で `HF_HOME` を、差し替える前の本物のキャッシュ（`HF_HOME` が設定済みならその値、なければ `~/.cache/huggingface`）に固定すること。

標準的なフィクスチャインポート:

```python
# tests/conftest.py
from n3memorycore.core.database import get_connection, init_db
from n3memorycore.core.processor import get_model
```

テスト内で `sys.path.insert(...)` を使用してはならない。`pip install -e ".[test]"` 後、リポジトリルートから:

```bash
python -m pytest tests/ -v
```

### Layer 1: `test_database.py`（27テスト）

| テストクラス | テスト内容 | カバレッジ |
|---|---|---|
| `TestSchema` | `tables_created`, `migrate_idempotent`, `add_missing_columns`, `fts_tokenizer_is_trigram`, `migrate_tokenizer_to_trigram` | スキーマ作成とマイグレーション（`session_id` / `turn_id` を含む） |
| `TestInsertAndRetrieve` | `insert_count`, `three_table_consistency`, `insert_without_embedding`, `rowid_returned` | CRUD と 3 テーブルの整合性 |
| `TestDelete` | `delete_three_tables`, `delete_nonexistent` | トランザクション保護された削除 |
| `TestDedup` | `exact_duplicate_detected`, `no_false_positive` | 完全一致の重複排除 |
| `TestUnindexed` | `vec_missing_detected`, `all_indexed` | 修復検出 |
| `TestFTS` | `punctuation_removal`, `short_query_skipped`, `basic_search`, `punctuation_tolerance`, `max_terms_limit` | FTS5 |
| `TestVectorSearch` | `vector_search_results`, `empty_db_vector_search` | KNN検索 |
| `TestRetentionAndRange` | `old_records_retained`, `no_gc_decrements_count`, `since_filter_excludes_old`, `until_filter_excludes_new` | Free は古い記録を消さない。時間範囲フィルタ（v1.5.0 より前の名前は `TestGC`） |
| `TestSerialization` | `roundtrip` | バイナリ変換 |

**`test_dedup_concurrent.py`（3 テスト、R04。モデル不要）**: `TestDedupConcurrent` — `concurrent_same_turn_saved_once`（2 つのスレッドがバリアで合わせて、同じ文と `turn_id` で `/buffer` の処理を呼ぶ：行は 1 つ、`ok` と `exact_duplicate` が 1 つずつ）、`same_text_other_turn_still_saved`（別の `turn_id` なら同じ文でも 2 行とも保存される）、`insert_memory_once_returns_none_for_a_duplicate`（同じ文と `turn_id` の 2 回目の挿入は `None` を返し、トランザクションを開いたままにせず、DB の行は 1 つ）。

### Layer 2: `test_processor.py`（24テスト）

| テストクラス | テスト内容 | カバレッジ |
|---|---|---|
| `TestCosineSim` | `identical_vectors`, `orthogonal_vectors`, `negative_clamped`, `midpoint` | L2→cosine変換 |
| `TestTimeDecay` | `current_time_is_one`, `half_life`, `floor_value`, `bad_timestamp_returns_one` | 半減期計算 |
| `TestKeywordRelevance` | `below_threshold_is_zero`, `full_relevance`, `partial_relevance`, `zero_max` | BM25正規化 |
| `TestPurification` | `code_block_replaced`, `inline_code_preserved`, `multiple_blocks_replaced`, `no_code_block_unchanged` | 複数行コードブロック → `[code omitted]`、インラインコードは保持 |
| `TestEmbedding` | `passage_embedding_shape`, `query_embedding_shape`, `same_text_similar` | Embeddingモデル |
| `TestRefresh` | `exact_duplicate_not_inserted`, `below_threshold_not_duplicate` | 重複の扱い（完全一致のみ） |
| `TestBiasScoring` | `session_match`, `session_mismatch_lower`, `full_score_formula` | ランキング式（`b_session` のみ。Free に `b_local` はない） |

### Layer 3: `test_api.py`（22テスト）

| テストクラス | テスト内容 | カバレッジ |
|---|---|---|
| `TestHealth` | `health_ok` | サーバー状態 |
| `TestBuffer` | `save_content`, `empty_content_skipped`, `agent_name_saved`, `exact_dedup`, `code_block_purified` | 保存API |
| `TestSearch` | `empty_db_search`, `save_then_search`, `empty_query`, `score_returned` | 検索API |
| `TestRepair` | `repair_runs`, `count_excludes_unrepaired_records` | 修復API。埋め込みを計算できないとき `count` は 0。`/repair` がバッチを埋め込んでいる間（1 件 0.2 秒の代役のモデル）に、別の接続が 0.5 秒以内に `BEGIN IMMEDIATE` を取れる。`BUSY_TIMEOUT_SECONDS` は 10（F11）。**2026-11-20（2 回目のレビュー）**：最初の修復が埋め込みを計算している間に、2 つ目の修復が同じ行を修復しても、どちらもエラーなく終わり、ベクトルは 1 つだけ残る。`_start_server` は、`/health` が別のフォルダを返すサーバーを使わない（`port_conflict`、False を返す） |
| `TestList` | `list_returns_records`, `list_after_save` | 一覧API |
| `TestDelete` | `delete_returns_403`, `delete_nonexistent_also_403`, `delete_detail_is_pro` | Pro 専用エンドポイント → 403 |
| `TestGC` | `gc_returns_403`, `gc_detail_is_pro` | Pro 専用エンドポイント → 403 |
| `TestImport` | `import_returns_403`, `import_with_data_returns_403`, `import_detail_is_pro` | Pro 専用エンドポイント → 403 |

### Layer 4: `test_hooks.py`（21テスト）と `test_hooks_encoding.py`（10テスト）

| テストクラス | テスト内容 | カバレッジ |
|---|---|---|
| `TestChunkText` | `short_text_single_record`, `long_text_multiple_chunks`, `prefixes_numbered`, `single_chunk_no_number`, `paragraph_split`, `hard_window_fallback` | 完全保存チャンク化 |
| `TestStripImages` | `plain_text_unchanged`, `base64_image_stripped`, `image_only_payload_returns_empty` | 画像ペイロード除去 |
| `TestExtractText` | `plain_string`, `multimodal_json_list`, `image_only_empty`, `empty_input`, `json_text_is_kept_as_typed` | マルチモーダル抽出。JSON として読める入力をマルチモーダルの配列として扱わない |
| `TestCompleteRecording` | `short_claude_response_saved`, `short_user_message_saved`, `skip_pattern_abolished`, `code_block_replaced_in_purify`, `inline_code_preserved_in_purify` | 完全記録契約（フィルタ廃止） |
| `TestStopIdempotency` | Codex の Stop | Codex の Stop を繰り返し実行してもプロジェクトの `AGENTS.md` は変更されず、記録は重複しないことを確認する。 |
| `TestSanitizerUnit` | `strips_lone_high_surrogate`, `strips_lone_low_surrogate`, `clean_japanese_unchanged`, `complete_emoji_pair_preserved`, `recursive_dict`, `recursive_list`, `none_passthrough` | サロゲート除去（`test_hooks_encoding.py`） |
| `TestSanitizedAcceptedBySQLite` | `sanitized_text_inserts_without_unicode_error` | 〃 |
| `TestPurifyAppliesSanitization` | `purify_strips_surrogates_alongside_code_blocks`, `purify_handles_empty` | 〃 |

> 上の件数は v1.4.0 のテスト一式のもの。v1.5.0 と v1.6.0 はテストを Layer 5 にだけ足すので、これらの表はそのまま有効。再生成したテスト一式と違う場合は、件数ではなく、ここにあるクラス名とテスト名に合わせること。

### Layer 5: `test_regressions.py`（v1.4.0〜v1.6.0）

埋め込みは `zlib.crc32` から作る決定論的な偽のベクトル（`fake_embed`）に差し替え、モデルなしで数秒で終わること。

| テストクラス | テスト内容 |
|---|---|
| `TestFtsQuoting` | `\ / # = @ * $ %`・`AND/OR/NOT`・`"`・制御文字を含むクエリで例外にならない、記号を含む語がヒットする、`search_fts` が例外を出しても `hybrid_search` が続く。**v1.5.0**: 語を `OR` でつなぐ（文のようなクエリが、その語の一部だけを含む記録にヒットする）、3 文字未満の語（`AI`、`東京`）は捨て、そういう語だけのクエリは FTS を飛ばす、クエリの句読点で語が分かれる（`「アルファ9」の気温は？` が `架空の惑星「アルファ9」の気温設定` にヒットする）。**2026-11-17**: 最大 40 語、CJK を含む 4 文字以上の語は 3 文字ずつに分ける |
| `test_search_port_2026_11_17.py`（2026-11-17） | 空白のない日本語の文が、その語を含む記録に当たる。ひらがなだけの 3 文字を捨てる。記号だけ・2 文字だけの質問で例外にならない。`bigram_text('N3MCの設定')` が `N3MC の設 設定`。`記憶` と `PR` がバイグラムの索引で（`hybrid_search` でも）当たる。バイグラムの検索が失敗しても trigram の結果が残る。`delete_memory` のあとバイグラムの行が残らない。`--repair` が古い DB のバイグラムの行を 1 回だけ埋める（2 回動かしても 1 記録 1 行）。`<agent-message from=...>` と `<system-reminder>` の入力は保存も検索もせず `turn_id` を変えない。`<agent-message` や `<div>` で始まるユーザーの質問は飛ばさない。返答との近さの並べ直しは既定で off、on なら返答の近い往復が上に来る、DB のエラーでは入力をそのまま返す |
| `test_index_meta.py`（v1.8.0） | （2026-11-22）`memories_vec` を `float[384]` で作り直し、`meta` の 3 行を消したあと、384 次元の代わりのモデルで `--reembed` が成功し、ベクトルの件数が記録の件数と一致し、`embed_dim` が 384 になる。次元が本当に違うモデルでは何も変えず exit 1。`init_db` が `meta` を作る。`/repair` が `fts_punct_cleaned` / `fts_bigram` / `embed_model` / `embed_dim` を書く。v1.7.0 の印のファイルの隣に戻した古いデータベース（`meta` のキーなし）でバイグラム索引が埋まる。`embed_model` を `vec_model.txt` から取るのはベクトルがあるときだけ。食い違いで `embed_model_mismatch` が出て、一致で消える。`--reembed` がすべてのベクトルを設定のモデルのものに替え、`embed_model` を書き、通知を消し、`reembed_cursor` から再開し、次元の違うモデルは何も変えずに断る |
| `test_review_2026_11_17.py`（2026-11-17） | どのチャンクも `max_chars` を超えない（段落と文の経路、`max_chars` が 400 と小さい値、日本語の文）。`chunk_text('x' * 10 + '\n\n' + 'y' * 400)` は 410 個の文字（`x` と `y`）をすべて残し、400 字以下のチャンクを返す。`is_own_hook` は、引用符なしで `\` 区切りの `C:\Tools\n3mc-hook.exe` と `C:\Tools\n3mc-stop-hook.exe` を自分のフックと認識し、`--init` はそのエントリを足さずに置き換える |
| `TestVectorFilter` | `since` 付きの検索で範囲内の記録が KNN の上位外にあっても返る、`rowid IN` が使えないときに全件計算に切り替わる |
| `TestNoSimilarityDedup` | 似た分割（cos ≥ 0.95）がすべて保存される、同じ `turn_id` の完全一致は飛ばす、別の `turn_id` の完全一致は保存する、`turn_id` なしは全体で完全一致を飛ばす |
| `TestSearchShaping` | `vector_min_cos` 未満の候補を捨てる、相対の足切り、`_version_group` は足切りで落ちない、新しい版が上に来る、同じ content の集約、`pair_top_n`・`pair_max_chars` と `pairs_omitted`。**v1.5.0**: 類似度の低い現在のセッションの記録があっても、類似度の高い 30 日前の別セッションの記録が相対の足切りで残る、別セッションのキーワードのみのヒットが `min_score` で残る、並びは今も最終スコア順（現在のセッションが先）。**v1.6.0**: 類似度の高い 400 日前の記録が、ほかに候補がなくても返る（`min_score` と相対の足切りは `time_decay` を見ない）、同じ類似度の新しい記録と 400 日前の記録が両方返り、新しいほうが上に来る |
| `TestRender` | `saved=` がローカル時刻、版の一文、省略の行に `--show-turn`、知らせが先頭に出る。**v1.6.0**: 弱い候補が Top matches の後、Q-A の往復の前に `## Possibly related (weak matches — may be unrelated)` の下に出て、番号は Top matches から続く、Top matches が 0 件なら `_No relevant memories found._` の後に弱い候補の見出しが出る（行は `[1]` から）、弱い候補がなければその見出しは出ない |
| `TestNoContextFile` | `--search` が `memory_context.md` を作らず、Codex の Stop がプロジェクト指針を変更しないことを確認する。 |
| `TestBehaviorMd` | 目印が同じなら触れない、過去のひな形なら控えを取って置き換える（**v1.6.0**: `v2` のひな形、ハッシュ `5af3c015c06c62c1` も含む。新しいファイルの 1 行目は `<!-- n3mc-behavior v3 -->` で、Weak Matches の節がある）、手で編集したものは置き換えず知らせを出す。**v1.5.0**: 知らせのキーにパスのハッシュが入り、メッセージにパスが入る、手で編集したファイルが 2 つあれば知らせも 2 つ、ファイルの 1 行目が今の目印になったら知らせが消える |
| `TestServerDecision` | 正常／`code_version` 違い／別のフォルダ／`root` なしで確かめられない、`/shutdown` を先に使う、`root` が違えば 403、死んだ PID ファイルは待たない。**2026-11-20**: PID ファイルのサーバーが別のポートで待ち受けていて、その `/health` がこのフォルダを返すときは、そのポートに `/shutdown` を送り、60 秒待たずに新しいサーバーを起動する。別の `root` を返すポートには `/shutdown` を送らない。`Host` の確認は、いまの `config.json` ではなく、サーバーが待ち受けているポートを使う |
| `TestServerStart`（v1.5.0） | 待っている間に終了した子プロセスでは待つのをすぐやめ、`server.log` を示す `server_start_failed` を出す、失敗から 5 分以内は新たに起動しない、あとで起動に成功したら知らせとマーカーが消える、60 秒たってもまだ起動中の PID ファイルのプロセスは入れ替えも重複起動もしない、`Popen` にプラットフォームに応じた切り離しのフラグが渡り stderr が `server.log` に行く（プロセスの作成は偽物に差し替え）、（2026-11-22）PID ファイルもサーバーもない状態で同時に始めた 2 つの `ensure_server` は `Popen` を 1 回だけ呼ぶ、予約した側の `Popen` が例外を出すと予約は消え、あとの呼び出しが起動できる、負けた側は PID ファイルを書き換えない、60 秒未満の空の PID ファイルは起動中とみなす |
| `TestServerApi`（v1.5.0） | `Host: evil.example` のリクエストはどのエンドポイントでも 403、`127.0.0.1:<port>` と `localhost:<port>` は通る、`/buffer`・`/search`・`/repair`・`/list` は普通の `def` 関数、`{"max_records": 200}` 付きの `/repair` は最大 200 件しか処理せず、`--hook-submit` はその上限を送る。`HTTP_PROXY` を別のローカルのサーバーに向けても、`_get` は N3MC のサーバーに届き、プロキシには何も届かない（F16）。**v1.9.1**: `Origin: http://evil.example` のリクエストと `Origin: null` のリクエストは、`Host: 127.0.0.1:<port>` でも、どのエンドポイントでも 403。同じリクエストから `Origin` を外すと通る。`_post` と `_get` が送るリクエストには `Origin` ヘッダーがない |
| `TestForeignServer` | 別のフォルダのサーバーのとき、保存は自分の DB に直接、検索はしない、`--repair` は何もしない |
| `TestConfig` | 読めない `config.json` を上書きしない、型の違う項目だけ無視、直したら知らせが消える、`config.json` の中身が変わったときだけ `code_version` が変わる。**v1.5.0**: `search_query_max_chars` の `2000.0`、`half_life_days` の `0`、`server_port` の `70000` / `-1`、`min_score` の `1.5` は `config_type` 付きで無視される（**v1.6.0**: `min_results` の `-1` と `1.5` も同じ。`0` は受け付ける。**C-06**: `search_result_limit` の `1366` も `config_type` で無視し、`1365` は受け付ける。`k = 4095` のベクトル検索は動く）、ないファイルは排他作成で作り、同時に作った別のプロセスのファイルは上書きせず読む（`owner_id` は 1 つ）、更新は一時ファイルと `os.replace` を通す、（2026-11-22）ID のない既存の `config.json`（DB は空）から同時に始めた 2 つのプロセスは、どちらもディスクの `owner_id` / `local_id` で終わり、利用者の設定は残る、何も変えなければサーバーの `code_version` はクライアントと一致し（キーを補って書いたあとも）、サーバーが読んだ直後に `config.json` を変えるとサーバーは `stale`、再起動後に新しい設定で `ok` |
| `TestHookSubmit` | Codex 入口がシステム入力を除外し、`session_id` と `turn_id` を使って保存し、トランスクリプトを再読込しないことを確認する。旧 CLI のトランスクリプト処理には別の互換テストがある。 |
| `TestPurifyBeforeChunk`（v1.5.0） | 2 つのコードブロックとその間の文章を持つ 500 字を超えるユーザー発言で、文章は残り、どちらのコードブロックも保存されない、400 字より長いコードブロックは保存されず置き換えられる |
| `TestChunkSentences`（v1.5.0） | 空行のない日本語の文章が、文の途中ではなく `。` / `！` / `？` のあとで分かれる |
| `TestTimeBounds`（v1.5.0） | 日付だけの `--since` はローカルの 0 時を UTC に直したもの（UTC 以外の固定のタイムゾーンで）、オフセット付きの値はそのオフセットを守る、`T` と空白の区切りで同じ境界になる、`yesterday` はエラーの行を出して終了ステータス 2、`since > until` はエラー |
| `TestDbCorrupt`（v1.5.0） | 2 回の破損で 2 つのバックアップ（`n3memory.db.corrupt-<time>.bak`）ができ、`-wal` / `-shm` は削除されずに隣へ移される、知らせ `db_corrupt` が出る、`quick_check` は 1 プロセスに 1 回。中身がごみのファイルと、先頭のページが壊れた DB は、次の直接保存と起動時の確認で退避され、`db_corrupt` の通知が出る。`OperationalError` と sqlite-vec の失敗は破損として扱わない（F13） |
| TestInit | テスト用 hooks.json で、ほかのフックの保持、冪等性、不正設定の保全、Windows の引用符、120 秒の設定を確認。 |
| `TestSaveFailedNotice`（2026-11-22） | 直接の保存が 1 回失敗したあと（`save_failed` がある）、サーバー経由の保存（`/buffer` を `ok` と答える偽物に差し替え）で知らせが消える。`skipped` と答えたときも消える |
| `TestHousekeeping`（v1.5.0） | `--stop` が 30 日より古い `turn_id_*.txt` を消し、新しいものは残す、50 MB を超えた `audit.log` を `audit.log.1` にローテーションする（テストではサイズのしきい値を差し替える） |
| `TestModelRetry`（v1.5.0） | モデルの読み込みに失敗したあと、`get_model()` は 60 秒間再試行しない（読み込み関数は偽物に差し替え）、`$N3MC_EMBED_MODEL` は効かない |
| `TestPackaging`（v1.5.0） | `psutil` が `pyproject.toml` の `dependencies` に入っている |
| `TestWeakMatches`（v1.6.0） | 下限を通った結果が 1 件で `min_results: 3` なら弱い候補が 2 件足され、`filter_score` の順に並び、`/search` で `"weak": true` が付き、普通の行の後に来る、`vector_min_cos` 未満の候補は実際の cos で足される（`filter_score` もその cos で計算）、`min_results: 0` では何も足さない、十分な件数が通ったときは足さない、`search_result_limit` が `min_results` より小さければ合計はその上限まで、結果の行と同じ content の候補や、すでに 2 件ある `turn_id` の候補は飛ばす、`filter_score` が `1e-6` 未満の候補（直交するベクトル）は足さない、弱い候補は `pairs` に使わない、空のクエリでは弱い候補も返さない |

### 安全なインポートパス: `test_safe_path.py`（2026-11-21。モデル不要）

プロセスを起動するテストは、どれも一時的なデータフォルダと一時的なホームフォルダを渡す。

| Test | 確かめること |
|---|---|
| `test_there_are_entry_modules` | メインのモジュールが、`if __name__ == "__main__":` で終わるモジュールの 1 つである。そうしたモジュールが 3 つ以上ある |
| `test_entry_module_starts_with_the_safe_path_block`（入口のモジュールごとに 1 回） | docstring のあとの最初の文が、`import os as _os`、`import sys as _sys`、`sys.path[0]` を消す `if __name__ == "__main__":` のブロックである |
| `test_files_in_the_current_folder_do_not_run` | `argparse.py`・`shlex.py`・`queue.py`・`fastapi.py`・`pydantic.py`・`sqlite_vec.py`・`numpy.py`・`uvicorn.py`（どれも、目印のファイルを書いて `ImportError` を出す）を置いたフォルダで、`python -m n3memorycore.n3memory --help` が使い方を出し、0 で終わり、目印を残さない |
| `test_without_the_block_they_would_run` | 同じフォルダで `python -c "import shlex"` を実行すると、目印が書かれる（上のテストが空振りでないことの確認） |
| `test_a_source_checkout_run_in_place_still_works` | リポジトリのルートから、`PYTHONPATH` なしで、`python -m n3memorycore.n3memory --help` が 0 で終わる |
| `test_children_are_started_with_dash_P_outside_a_checkout` | `python_cmd()` は、ほかのフォルダでは Python 3.11 以降で `[sys.executable, "-P"]`（3.10 では `[sys.executable]`）、リポジトリのルートでは `[sys.executable]` になる |
| `test_no_child_is_started_without_python_cmd` | パッケージのどのモジュールにも `[sys.executable,` がない |

### 実行方法

```bash
# 全テスト
python -m pytest tests/ -v

# 単一レイヤー
python -m pytest tests/test_database.py -v

# TestEmbedding を飛ばす（test_api.py はモデルを読み込む）
python -m pytest tests/ -v -k "not TestEmbedding"

# Embedding モデルなしで（オフライン、または初回のダウンロード前）
python -m pytest tests/ -v --ignore=tests/test_api.py -k "not TestEmbedding"
```

> **⚠️ Evidence Report との関係**: 自動テストの不合格は §6 の ⭐⭐⭐⭐⭐ 評価をブロックしない。Evidence Report が実装完了の唯一の合否基準である。自動テストは開発者が任意で実行する補助的な回帰テストであり、初回実装時に無限の修正・再試行ループを引き起こしてはならない。

---

## 📎 参考: GPU アクセラレーション

> **Codex Free 版**: 現行実装は埋め込みを CPU に固定しています。以下は元の指示書の参考情報です。記載の PyTorch 入れ替えだけでは GPU に切り替わりません。

> 現在のデフォルト構成（768次元 multilingual-e5-base モデル、embedding 1回/プロンプト）では CPU で十分高速に動作するため、GPU は不要です。
> 1024次元モデルへの切り替えや、速度が気になる場合に検討してください。

NVIDIA CUDA 対応 GPU がある場合、以下のコマンドで高速化できる可能性があります：

```
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

- `sentence-transformers` は内部で PyTorch を使用しており、GPU 版 PyTorch がインストールされていれば embedding 推論は自動的に GPU 上で実行されます（コード変更不要）
- コールドスタート（サーバー起動直後）: CPU で約 1〜1.5 秒/回 → ウォーム状態で約 0.03〜0.06 秒/回
- GPU では約 0.02〜0.05 秒/回に短縮される可能性があります

---

## 付録：推奨開発ワークフロー

> **この付録は人間向けの操作ガイドです。** 各フェーズで ``` 内のプロンプトをコピーして Codex に貼り付けてください。AI が自動で次のフェーズに進むことはありません。

| フェーズ | あなたがやること | 使うモデル |
|---|---|---|
| 1. 実装 | プロンプトを貼って実装を依頼 | **Sol**（高速） |
| 2. デバッグ | 3 つのプロンプトを**順番に**貼って検証 | **Sol** |
| 3. 品質レビュー | **新しいセッションを始めてから**、プロンプトを貼って評価・改善を依頼 | **Astra**（深い推論） |

---

### フェーズ 1：実装（Sol）

モデルを **Sol** に設定し、以下を貼り付けてください。

```
この指示書に従って N3MemoryCore を実装してください。
```

Sol がコード生成と隔離環境での検証を行います。実機フックは §6 のテスト 7 に沿って利用者が信頼します。完了したらフェーズ 2 に進んでください。

---

### フェーズ 2：デバッグ（Sol）

引き続き **Sol** で、以下の 3 つのプロンプトを**順番に 1 つずつ**貼り付けてください。

**① データフロートレース**（データが途中で失われていないか確認）
```
N3MemoryCore について：
コードを読んで、検索クエリから Codex へのエンドツーエンドのデータフローをトレースしてください。
途中でデータが失われている箇所がないか確認してください。
必要に応じて修正してください。
```

**② 仕様との逐条比較**（指示書に書いてあるのに未実装の動作がないか確認）
```
N3MemoryCore について：
指示書の各 CLI コマンドの入出力仕様を、実際のコードと 1 コマンドずつ比較してください。
ドキュメントに記載されているが実装されていない動作を探してください。
必要に応じて修正してください。
```

**③ クロスセッションテスト**（セッションを跨いでデータが見えるか実行確認）
```
N3MemoryCore について：
セッション 1 で --buffer で保存した結果が、セッション 2 で --search を使うと Codex から見えるかどうかを、実際にコマンドを実行して確認してください。
必要に応じて修正してください。
```

3 つとも完了したらフェーズ 3 に進んでください。

---

### フェーズ 3：品質レビュー（Astra）

> **⚠️ レビューは新しいセッションで行う**: 実装とデバッグを行ったセッションでレビューしないでください。Codex を終了し、同じインストール先のフォルダで起動し直して、新しいセッションを始めてください。
> - 実装したセッションのコンテキストには、そのセッション自身の判断や説明が残っています。そこでレビューすると、コードと指示書を改めて突き合わせるより、それまでの判断を追認しがちになります。
> - Codex を起動し直すと、セットアップで登録したフックも読み込まれます。そのため、利用者が使うときと同じ状態で記憶の動きをレビューできます。
> - 新しいセッションでは、フックが実装時の会話の一部を思い出すことがあります。これは想定どおりです。レビューは、コード、この指示書、実際に実行したコマンドの結果にもとづいて行ってください。

新しいセッションで、モデルを **Astra** に切り替え、以下を貼り付けてください。

```
N3MemoryCore をレビューしてください。
必要に応じて修正してください。

N3MemoryCore は記憶装置と RAG として 10 点満点で何点ですか？
記憶装置としての評価と RAG としての評価を分けて、スコアカードを生成してください。
```

Astra が実際にコマンドを実行し、**記憶装置**（保存・永続性・重複排除）と **RAG**（検索精度・ランキング・ノイズ耐性）の 2 軸でスコアカードを生成します。

> **注意**：記憶装置としては高評価が期待できますが、RAG としては基本実装のため以下が未実装で **RAG 側は 7 点を超えることはまずありません：**
> - 形態素解析（日本語なら MeCab / SudachiPy 等）による適切なトークン分割
> - 言語特化 embedding モデル（multilingual-e5-large 等）への切り替え
> - 高度なチャンキング戦略（言語・文書構造に応じた分割）
> - リランキング（Cross-Encoder、Cohere Rerank、LLM 等による検索結果の再順位付け）
>
> 甘い採点は改善機会を失わせるため、厳格に評価してください。**スコアに関わらず、Astra に何が足りないかを具体的に指摘してもらい、改善点を必ず相談してください。**

---

Copyright (C) 2026 NeuralNexusNote™ / ArnolfJp019
All names and logos associated with N3MemoryCore and NeuralNexusNote are trademarks of the author.
