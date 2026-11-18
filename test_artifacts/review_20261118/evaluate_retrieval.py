"""Small, disclosed retrieval smoke benchmark; not a general RAG accuracy claim.

Run from repository root with: python test_artifacts/review_20261118/evaluate_retrieval.py
Uses only synthetic records and the cached multilingual-e5-base model.
"""
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

from n3memorycore import n3memory
from n3memorycore.core import database as db, processor as proc

# id, question, answer, age in days. All facts are fictional.
CORPUS = [
    ('penguin', '合言葉を覚えてください。', '検証用の合言葉は銀河ペンギン7319です。', 2),
    ('meeting', 'カシオペア計画の会議予定です。', 'カシオペア計画の会議は毎週水曜日の午後3時です。', 5),
    ('budget', '青葉商店の予算を記録してください。', '青葉商店の広告予算は月額48,000円です。', 7),
    ('backup', 'データの保管方法を決めました。', '業務データは毎晩午前2時に外付けSSDへバックアップします。', 8),
    ('preference', '回答の形式について希望があります。', '回答は日本語で、結論を先に述べ、箇条書きを3項目以内にしてください。', 9),
    ('deadline', '北斗展示会の申込締切を共有します。', '北斗展示会の申込締切は2026年12月5日です。', 3),
    ('old_price', 'ルミナ製品の料金を登録します。', 'ルミナ製品の月額料金は980円です。', 30),
    ('new_price', 'ルミナ製品の料金を訂正します。', 'ルミナ製品の月額料金を1,480円へ変更しました。以前の980円は廃止です。', 1),
    ('storage', 'サンプルアプリのDBを決めました。', 'サンプルアプリはPostgreSQLを使い、接続ポートは5433です。', 4),
    ('allergy', '食事の注意事項です。', '架空ユーザーのミカには卵アレルギーがあります。', 6),
    ('location', '打ち合わせ場所を記録してください。', '月影工房との打ち合わせは盛岡駅西口の会議室Bで行います。', 4),
    ('shipping', '発送方法を設定しました。', '海外向けのサンプル発送にはDHLを利用します。', 4),
    ('old_fact', '長期保存する設備の情報です。', '星雲倉庫の非常用電源の型番はNX-420です。', 365),
    ('tea', '飲み物についてです。', '休憩時にはほうじ茶を飲みます。', 2),
    ('garden', '花壇の作業を決めました。', '花壇にはチューリップの球根を植えます。', 2),
    ('train', '出張の移動方法です。', '出張には東北新幹線を利用します。', 2),
    ('camera', '撮影機材を記録します。', '撮影には焦点距離35mmのレンズを使います。', 2),
    ('font', '印刷物の指定です。', '印刷物の本文は12ポイントの明朝体です。', 2),
    ('holiday', '店舗の休業日です。', '山猫書店は毎週月曜日が定休日です。', 2),
    ('delivery', '配送の目安です。', '国内の注文は通常3営業日以内に発送します。', 2),
]

# question, relevant turn, evidence string. None means corpus has no answer.
QUERIES = [
    ('銀河ペンギンの合言葉は何ですか？', 'penguin', '7319'),
    ('カシオペア計画の会議は何曜日の何時？', 'meeting', '水曜日'),
    ('青葉商店の広告予算はいくら？', 'budget', '48,000'),
    ('データのコピーはいつ、どの媒体に取ることにした？', 'backup', '外付けSSD'),
    ('私が希望する返答の書き方は？', 'preference', '結論を先に'),
    ('北斗展示会の申し込みはいつまで？', 'deadline', '12月5日'),
    ('ルミナ製品の現在の月額料金はいくら？', 'new_price', '1,480'),
    ('サンプルアプリのDBポートは？', 'storage', '5433'),
    ('ミカの食事で避けるべき食材は？', 'allergy', '卵'),
    ('Where do we meet the Tsukikage workshop?', 'location', '盛岡駅西口'),
    ('Which courier handles our overseas samples?', 'shipping', 'DHL'),
    ('星雲倉庫の非常用電源の型番を教えて', 'old_fact', 'NX-420'),
    ('私が飼っている猫の名前は？', None, None),
    ('来年の国際ピアノコンクールの優勝者は？', None, None),
    ('火星基地の酸素濃度の測定値は？', None, None),
    ('量子暗号装置の故障原因は？', None, None),
]


def evaluate(path, config):
    rows = []
    for query, relevant, evidence in QUERIES:
        start = time.perf_counter()
        result = proc.hybrid_search(str(path), query, config, current_session_id='new-chat')
        elapsed = time.perf_counter() - start
        strong = [r for r in result['results'] if not r.get('weak')]
        turns = list(dict.fromkeys(r['turn_id'] for r in strong))
        all_turns = list(dict.fromkeys(r['turn_id'] for r in result['results']))
        rank = turns.index(relevant) + 1 if relevant in turns else None
        rendered = proc.render_memory_context(result, query)
        rows.append(dict(query=query, relevant=relevant, rank=rank,
                         top_turns=turns[:5], all_turns=all_turns,
                         strong_count=len(strong), weak_count=len(result['results'])-len(strong),
                         evidence_in_context=bool(evidence and evidence in rendered),
                         elapsed_seconds=round(elapsed, 4), context_chars=len(rendered)))
    positives = [r for r in rows if r['relevant']]
    negatives = [r for r in rows if not r['relevant']]
    return dict(
        summary=dict(answerable=len(positives), unanswerable=len(negatives),
                     hit_at_1=sum(r['rank'] == 1 for r in positives)/len(positives),
                     hit_at_3=sum(r['rank'] is not None and r['rank'] <= 3 for r in positives)/len(positives),
                     mrr=sum(1/r['rank'] if r['rank'] else 0 for r in positives)/len(positives),
                     evidence_in_context=sum(r['evidence_in_context'] for r in positives)/len(positives),
                     no_strong_result_rate=sum(r['strong_count'] == 0 for r in negatives)/len(negatives),
                     any_result_on_unanswerable=sum(bool(r['all_turns']) for r in negatives),
                     median_query_seconds=statistics.median(r['elapsed_seconds'] for r in rows),
                     max_context_chars=max(r['context_chars'] for r in rows)), rows=rows)


def main():
    output = Path(__file__).parent
    config = dict(n3memory._DEFAULT_CONFIG)
    start = time.perf_counter()
    model = proc.get_model(config['embed_model'])
    load_seconds = time.perf_counter() - start
    records = [(tid, role, text, age) for tid, q, a, age in CORPUS
               for role, text in [('user', q), ('claude', a)]]
    start = time.perf_counter()
    vectors = model.encode(['passage: [' + role + '] ' + text
                            for _, role, text, _ in records], normalize_embeddings=True)
    embed_seconds = time.perf_counter() - start
    with tempfile.TemporaryDirectory(prefix='retrieval-', dir=output) as tmp:
        path = Path(tmp) / 'synthetic.db'
        conn = db.get_connection(str(path))
        db.init_db(conn)
        now = datetime.now(timezone.utc)
        for i, ((tid, role, text, age), vec) in enumerate(zip(records, vectors)):
            db.insert_memory(conn, f'{tid}-{role}', f'[{role}] {text}',
                             (now-timedelta(days=age)).isoformat(), 'synthetic-owner',
                             embedding=list(vec), session_id=f'chat-{tid}', turn_id=tid,
                             agent_name='synthetic')
        conn.close()
        measured = evaluate(path, config)
        original = proc.embed_query
        def unavailable(_):
            raise RuntimeError('deliberate offline failure for benchmark')
        proc.embed_query = unavailable
        try:
            keyword_only = evaluate(path, config)
        finally:
            proc.embed_query = original
    report = dict(model=config['embed_model'], config=config, records=len(records),
                  model_load_seconds=round(load_seconds, 3),
                  corpus_embedding_seconds=round(embed_seconds, 3),
                  corpus=CORPUS, hybrid=measured, keyword_only=keyword_only)
    (output / 'retrieval_results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({mode: report[mode]['summary'] for mode in ('hybrid', 'keyword_only')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
