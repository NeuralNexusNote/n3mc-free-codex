# SQLite backup / バックアップ

N3MemoryCore uses WAL mode. Committed writes can reside in `n3memory.db-wal` before checkpointing. Do not copy only the live main database or independently copy changing WAL sidecars.

WAL モードでは、保存済みの更新が `n3memory.db-wal` に残ることがあります。稼働中の DB 本体だけ、または更新中のサイドカーファイルを個別にコピーする方法は避けてください。

Run the following Python code with the same `N3MC_HOME` as the installation. It creates a new timestamped folder in the working directory and uses SQLite's consistent online backup API. Keep configuration unchanged during the operation. No embedding model is needed.

対象のインストールと同じ `N3MC_HOME` を設定した Python で実行します。作業ディレクトリに日時付きの新規フォルダーを作成します。処理中は設定を変更しないでください。モデルの読み込みは不要です。

```python
from datetime import datetime
from pathlib import Path
import os
import shutil
import sqlite3

home = Path(os.environ.get('N3MC_HOME', '~/.n3mc')).expanduser().resolve()
source = home / '.memory' / 'n3memory.db'
destination = Path('n3mc-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
destination.mkdir()  # Refuse to overwrite an existing backup.
src = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
dst = sqlite3.connect(destination / 'n3memory.db')
try:
    src.backup(dst)
    assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
finally:
    dst.close()
    src.close()
shutil.copy2(home / 'config.json', destination / 'config.json')
print(destination.resolve())
```

Restore into a **new, empty N3MC home**, with its server and hooks stopped: place the snapshot at `.memory/n3memory.db` and configuration at `config.json`, then configure CLI and hooks to use that home. This avoids mixing a restored database with stale `-wal` / `-shm` files. Verify the record count and selected turns before resuming normal capture. Retain the original data until verification succeeds. `n3mc --stop` performs housekeeping; it does **not** shut down the server.

復元はサーバー・フックが停止した**新しい空の保存先**へ行います。DB を `.memory/n3memory.db`、設定を `config.json` に配置し、CLI とフックの保存先を揃えます。古い `-wal` / `-shm` との混在を防ぎ、件数と代表的なターンを確認してから通常運用へ戻してください。確認が済むまで元データを保管します。`n3mc --stop` は後片付けであり、サーバー停止コマンドではありません。
