# N3MemoryCore Free / Codex セットアップ

[English](README.md) · [再作成用の指示書](N3MemoryCore_v1.9.1_Free_JP.md)

N3MemoryCore Free はローカル Codex の入力と最終応答を保存します。入力のたびにローカル SQLite を検索し、新しいチャットでも過去の関連記録を使えます。

```sh
python -m pip install -e ".[test]"
n3mc --init
```

Free のソースリポジトリで、使い続ける Python 環境から実行します。`/hooks` で両フックを確認して信頼し、新しいチャットを開きます。再作成する場合は、上の指示書を Codex に渡し、専用フォルダを指定して実装を依頼してください。

データは既定で `~/.n3mc` に保存されます。`N3MC_HOME` で変更できます。関連する記録だけがフックからチャットに渡されます。保存しない依頼と検知した認証情報はフックの保存対象外です。期限による自動削除はありません。

登録先は `$CODEX_HOME/hooks.json`（既定 `~/.codex/hooks.json`）です。利用前に、同一チャットの複数ターンと別チャットからの取り出しを確認してください。検証時は `N3MC_CODEX_HOOKS_PATH` でフック設定を隔離できます。

この配布フォルダには再作成用の指示書が含まれます。実装・デバッグは **Sol**、レビューは **Astra** を推奨します。
