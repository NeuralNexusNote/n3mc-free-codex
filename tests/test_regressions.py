"""Layer 5: regression tests for v1.4.0 - v1.9.1 fixes. The embedding is faked: no model, a few seconds."""
import io
import json
import os
import sqlite3
import sys
import time
import tomllib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from n3memorycore_free_codex import n3memory as n3m
from n3memorycore_free_codex.core import database as db
from n3memorycore_free_codex.core import processor as p

from .conftest import add, fake_embed

NOW = datetime.now(timezone.utc)


def ago(days):
    return (NOW - timedelta(days=days)).isoformat()


def search(conn, cfg, q, **kw):
    return p.hybrid_search(conn, q, cfg, embed_fn=fake_embed, **kw)


class TestFtsQuoting:
    @pytest.mark.parametrize("q", [r'C:\Users\test #tag = @a * $b % AND OR NOT "q"', "NEAR( x )", "a\x00b\x1fc",
                                   "!!! ??? ...", "AND", '"""'])
    def test_symbols_never_raise(self, conn, cfg, q):
        add(conn, cfg, "plain text about symbols and tags")
        db.search_fts(conn, q)
        search(conn, cfg, q)

    def test_symbol_word_hits(self, conn, cfg):
        add(conn, cfg, "path C:/Users/test/#tag here")
        assert db.search_fts(conn, "test/#tag")

    def test_hybrid_survives_fts_exception(self, conn, cfg, monkeypatch):
        add(conn, cfg, "the quick brown fox")
        monkeypatch.setattr(p, "search_fts", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("x")))
        assert search(conn, cfg, "the quick brown fox")["results"]

    def test_or_semantics(self, conn, cfg):
        add(conn, cfg, "the quick brown fox", embed=False)
        assert db.search_fts(conn, "what is the quick fox doing in my DB")

    def test_short_terms_dropped(self):
        assert db._build_fts_query("AI 東京") == ""

    def test_punctuation_splits_terms(self, conn, cfg):
        add(conn, cfg, "架空の惑星「アルファ9」の気温設定", embed=False)
        assert db.search_fts(conn, "「アルファ9」の気温は？")

    def test_cjk_terms_split_in_trigrams(self):
        q = db._build_fts_query("アルファ9の気温")
        assert '"アルフ"' in q and '"の気温"' in q and " OR " in q

    def test_max_terms(self):
        assert db._build_fts_query(" ".join(f"term{i:03d}" for i in range(80))).count(" OR ") == 39


class TestVectorFilter:
    def test_since_returns_in_range_records_outside_global_top_k(self, conn, cfg):
        for i in range(8):
            add(conn, cfg, f"fox story number {i}", ts="2020-01-01T00:00:00+00:00")
        add(conn, cfg, "fox story recent", ts="2026-06-01T00:00:00+00:00")
        hits = db.search_vector(conn, fake_embed("fox story"), k=3, since="2026-01-01T00:00:00+00:00")
        assert [h[0]["content"] for h in hits] == ["fox story recent"]

    def test_falls_back_to_exact_scan(self, conn, cfg, monkeypatch):
        add(conn, cfg, "fox story recent", ts="2026-06-01T00:00:00+00:00")
        real = conn.execute

        class Wrap:
            def __init__(self, c):
                self.c = c

            def execute(self, sql, *a):
                if "MATCH" in sql and "rowid IN" in sql:
                    raise sqlite3.OperationalError("unsupported")
                return self.c.execute(sql, *a)

            def __getattr__(self, n):
                return getattr(self.c, n)

        hits = db.search_vector(Wrap(conn), fake_embed("fox story"), k=3, since="2026-01-01T00:00:00+00:00")
        assert hits and hits[0][0]["content"] == "fox story recent"


class TestNoSimilarityDedup:
    def test_similar_chunks_all_saved(self, conn, cfg):
        for i in range(3):
            assert n3m._store_record(conn, cfg, f"[claude {i + 1}/3] 設定の値は{i}です。残りは同じ文章です。", turn_id="T",
                                     embed=False)["status"] == "ok"
        assert db.count_memories(conn) == 3

    def test_exact_scopes(self, conn, cfg):
        n3m._store_record(conn, cfg, "same", turn_id="A", embed=False)
        assert n3m._store_record(conn, cfg, "same", turn_id="A", embed=False)["status"] == "skipped"
        assert n3m._store_record(conn, cfg, "same", turn_id="B", embed=False)["status"] == "ok"
        n3m._store_record(conn, cfg, "manual", embed=False)
        assert n3m._store_record(conn, cfg, "manual", embed=False)["status"] == "skipped"


class TestSearchShaping:
    def test_vector_min_cos_drops_unrelated(self, conn, cfg):
        add(conn, cfg, "alpha beta gamma delta")
        add(conn, cfg, "zzz qqq www xxx")
        res = search(conn, cfg, "alpha beta gamma delta", )["results"]
        assert [r["content"] for r in res if not r["weak"]] == ["alpha beta gamma delta"]

    def test_old_other_session_record_survives_relative_cut(self, conn, cfg):
        base = "unique zebra aardvark sentence about fast river crossing during dawn light today"
        add(conn, cfg, base.replace("today", "now"), session_id="s1")
        add(conn, cfg, base, session_id="s2", ts=ago(30))  # 30 days old, other session, cos ~0.9
        res = [r for r in search(conn, cfg, base.replace("today", "now"), session_id="s1")["results"]
               if not r["weak"]]
        assert len(res) == 2 and res[0]["session_id"] == "s1"

    def test_other_session_keyword_only_hit_survives_min_score(self, conn, cfg):
        add(conn, cfg, "kiwi marmalade ledger", session_id="other", embed=False)
        res = search(conn, cfg, "kiwi marmalade ledger", session_id="mine")["results"]
        assert res and res[0]["cos_sim"] == 0.0 and not res[0]["weak"]

    def test_old_records_are_returned(self, conn, cfg):
        add(conn, cfg, "vintage zebra aardvark record", ts=ago(400))
        res = search(conn, cfg, "vintage zebra aardvark record")["results"]
        assert res and not res[0]["weak"]

    def test_newer_ranks_above_older_same_similarity(self, conn, cfg):
        base = "duplicate topic about zebra stripes seen near the wide river bank today"
        add(conn, cfg, base, ts=ago(400), turn_id="old")
        add(conn, cfg, base.replace("today", "now"), ts=ago(1), turn_id="new")
        res = [r for r in search(conn, cfg, base)["results"] if not r["weak"]]
        assert len(res) == 2 and res[0]["turn_id"] == "new"

    def test_pair_top_n_and_max_chars(self, conn, cfg):
        for t in "ABCDE":
            add(conn, cfg, f"[user] zebra question {t}", turn_id=t)
            add(conn, cfg, f"[claude] " + ("answer " * 100), turn_id=t)
        out = search(conn, cfg, "zebra question")
        assert len(out["pairs"]) <= cfg["pair_top_n"]
        assert sum(len(s["content"]) for v in out["pairs"].values() for s in v) <= cfg["pair_max_chars"]

    def test_pairs_omitted_when_first_row_too_big(self, conn, cfg):
        cfg = {**cfg, "pair_max_chars": 10}
        add(conn, cfg, "[user] zebra question about stripes", turn_id="A")
        out = search(conn, cfg, "zebra question about stripes")
        assert out["pairs"] == {} and out["pairs_omitted"] == {"A": 1}

    def test_version_ordering_newest_first(self, conn, cfg):
        body = "設定の本文 " * 30
        add(conn, cfg, "[user] 設定を作成して", turn_id="old", ts=ago(5))
        add(conn, cfg, "[claude] " + body + "旧", turn_id="old", ts=ago(5))
        add(conn, cfg, "[user] 設定を作成して", turn_id="new", ts=ago(1))
        add(conn, cfg, "[claude] " + body + "新", turn_id="new", ts=ago(1))
        res = search(conn, cfg, "設定を作成して 設定の本文")["results"]
        turns = [r["turn_id"] for r in res if r["turn_id"]]
        assert turns.index("new") < turns.index("old")

    def test_identical_content_collapsed_keeping_newest(self, conn, cfg):
        add(conn, cfg, "same words everywhere here", turn_id="a", ts=ago(9))
        add(conn, cfg, "same words everywhere here", turn_id="b", ts=ago(1))
        res = [r for r in search(conn, cfg, "same words everywhere here")["results"]]
        assert len(res) == 1 and res[0]["turn_id"] == "b"

    def test_at_most_two_chunks_per_turn(self, conn, cfg):
        for i in range(5):
            add(conn, cfg, f"[claude {i + 1}/5] zebra stripes chunk {i}", turn_id="T")
        res = search(conn, cfg, "zebra stripes chunk")["results"]
        assert len([r for r in res if r["turn_id"] == "T"]) <= 2


class TestRender:
    def _res(self, **kw):
        base = {"id": "1", "content": "hello", "score": 0.5, "timestamp": "2026-11-13T01:34:56.123456+00:00",
                "turn_id": "T", "agent_name": "claude-code", "weak": False}
        return {**base, **kw}

    def test_saved_is_local_time_with_offset(self):
        out = p.render_memory_context("q", [self._res()])
        assert "saved=" in out and "(UTC" in out and "newest `saved` time" in out

    def test_omitted_line_names_show_turn(self):
        out = p.render_memory_context("q", [self._res()], {"T": [{"id": "1", "content": "x", "timestamp":
                                      "2026-11-13T01:34:56+00:00"}]}, {"T": 3})
        assert "3 more chunk(s) of this exchange omitted" in out and "--show-turn T" in out

    def test_notice_comes_first(self):
        out = p.render_memory_context("q", [self._res()], notices=["fix me"])
        assert out.index("N3MC notice: fix me") < out.index("## Top matches")

    def test_weak_after_top_and_numbering_continues(self):
        out = p.render_memory_context("q", [self._res(), self._res(weak=True, content="weakone")])
        assert out.index("## Top matches") < out.index("## Possibly related") < out.index("weakone")
        assert "## [1]" in out and "## [2]" in out

    def test_only_weak(self):
        out = p.render_memory_context("q", [self._res(weak=True)])
        assert "_No relevant memories found._" in out and "## [1]" in out and "## Top matches" not in out

    def test_no_weak_no_heading(self):
        assert "Possibly related" not in p.render_memory_context("q", [self._res()])


def test_search_does_not_create_memory_context(tmp_path):
    n3m.cmd_search("context")
    assert not (tmp_path / "n3mc_home" / ".memory" / "memory_context.md").exists()


class TestServerDecision:
    def test_decisions(self, monkeypatch):
        cv = n3m.compute_code_version()
        assert n3m._health_decision(None) == "none"
        assert n3m._health_decision({"status": "ok", "root": n3m.HOME_DIR, "code_version": cv}) == "ok"
        assert n3m._health_decision({"status": "ok", "root": n3m.HOME_DIR, "code_version": "x"}) == "stale"
        assert n3m._health_decision({"status": "ok", "root": "/elsewhere", "code_version": cv}) == "foreign"
        assert n3m._health_decision({"status": "ok"}) == "legacy"

    def test_code_version_changes_with_config_content_only(self):
        n3m._load_config()
        a = n3m.compute_code_version()
        cfg = json.load(open(n3m.CONFIG_FILE))
        open(n3m.CONFIG_FILE, "w").write(json.dumps(cfg, indent=8, sort_keys=True))
        assert n3m.compute_code_version() == a
        cfg["min_score"] = 0.3
        open(n3m.CONFIG_FILE, "w").write(json.dumps(cfg))
        assert n3m.compute_code_version() != a

    def test_stale_server_stopped_with_shutdown_first(self, monkeypatch):
        calls = []
        monkeypatch.setattr(n3m, "_get_health", lambda port=None: {"status": "ok", "root": n3m.HOME_DIR,
                                                                    "code_version": "old", "pid": 1})
        monkeypatch.setattr(n3m, "_request_shutdown", lambda *a, **k: calls.append("shutdown") or True)
        monkeypatch.setattr(n3m, "_wait_port_free", lambda *a, **k: True)
        monkeypatch.setattr(n3m, "_launch", lambda: calls.append("launch") or True)
        assert n3m.ensure_server() is True and calls == ["shutdown", "launch"]

    def test_foreign_server_not_used_or_stopped(self, monkeypatch):
        monkeypatch.setattr(n3m, "_get_health", lambda port=None: {"status": "ok", "root": "/other/home",
                                                                    "code_version": "x", "pid": 1})
        called = []
        monkeypatch.setattr(n3m, "_request_shutdown", lambda *a, **k: called.append(1))
        assert n3m.ensure_server() is False and n3m._FOREIGN_SERVER_ROOT == "/other/home" and not called
        assert "port_conflict" in n3m._notices_read()

    def test_dead_pid_file_is_removed_without_waiting(self, monkeypatch):
        open(n3m.PID_FILE, "w").write("999999")
        monkeypatch.setattr(n3m, "_get_health", lambda port=None: None)
        monkeypatch.setattr(n3m, "_launch", lambda: True)
        t = time.time()
        assert n3m.ensure_server() is True and time.time() - t < 5 and not os.path.exists(n3m.PID_FILE)

    def test_shutdown_endpoint_checks_root(self, use_fake_embed, monkeypatch):
        monkeypatch.setattr(n3m, "_exit_server", lambda: None)
        c = TestClient(n3m.create_app(), base_url="http://127.0.0.1:18526")
        assert c.post("/shutdown", json={"root": "/wrong"}).status_code == 403
        assert c.post("/shutdown", json={"root": n3m.HOME_DIR}).json() == {"status": "ok"}

    def test_host_check_uses_the_servers_own_port(self, use_fake_embed, monkeypatch):
        monkeypatch.setattr(n3m, "_SERVER_PORT", 19999)
        c = TestClient(n3m.create_app(), base_url="http://127.0.0.1:19999")
        assert c.get("/health").status_code == 200  # config.json says 18526, the server listens on 19999


class TestServerStart:
    def test_early_exit_is_reported_with_server_log(self, monkeypatch):
        class Proc:
            pid, returncode = 4242, 3

            def poll(self):
                return 3

        monkeypatch.setattr(n3m, "_start_server", _real_start_server)
        monkeypatch.setattr(n3m.subprocess, "Popen", lambda *a, **k: Proc())
        monkeypatch.setattr(n3m, "_get_health", lambda port=None: None)
        assert n3m._start_server() is False
        assert "server_start_failed" in n3m._notices_read() and n3m.SERVER_LOG in n3m._notices_read()[
            "server_start_failed"]["message"]
        assert os.path.exists(n3m.SERVER_START_FAILED_FILE)
        monkeypatch.setattr(n3m, "_start_server", lambda: (_ for _ in ()).throw(AssertionError("retried")))
        assert n3m._launch() is False  # within 5 minutes: not tried again

    def test_popen_gets_detach_flags_and_server_log(self, monkeypatch):
        seen = {}

        class Proc:
            pid, returncode = 4243, None

            def poll(self):
                return None

        def fake_popen(cmd, **kw):
            seen.update(cmd=cmd, **kw)
            return Proc()

        monkeypatch.setattr(n3m, "_start_server", _real_start_server)
        monkeypatch.setattr(n3m.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(n3m, "SERVER_WAIT_SECONDS", 0)
        n3m._start_server()
        assert seen["cmd"][-3:] == ["-m", "n3memorycore_free_codex.n3memory", "--run-server"] or seen["cmd"][-1] == "--run-server"
        if os.name == "nt":
            assert seen["creationflags"] & n3m.subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            assert seen["start_new_session"] is True
        assert seen["stderr"].name == n3m.SERVER_LOG

    # ---- 2026-11-22, review #5: the PID file is reserved before Popen
    @staticmethod
    def _proc(pid):
        class Proc:
            returncode = None

            def poll(self):
                return None
        p_ = Proc()
        p_.pid = pid
        return p_

    def test_two_concurrent_ensure_server_calls_popen_once(self, monkeypatch):
        import threading
        started = threading.Event()
        calls = []

        def fake_popen(cmd, **kw):
            calls.append(1)
            time.sleep(0.5)  # the other call runs into the reservation meanwhile
            started.set()
            return self._proc(4242)

        def health(port=None):
            return ({"status": "ok", "root": n3m.HOME_DIR, "code_version": n3m.compute_code_version(), "pid": 4242}
                    if started.is_set() else None)

        n3m.get_config()
        monkeypatch.setattr(n3m, "_start_server", _real_start_server)
        monkeypatch.setattr(n3m.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(n3m, "_get_health", health)
        monkeypatch.setattr(n3m, "_pid_is_own", lambda pid: True)  # the fake child is this folder's server
        barrier, results = threading.Barrier(2), []

        def run():
            barrier.wait()
            results.append(n3m.ensure_server())

        ts = [threading.Thread(target=run) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        assert results == [True, True] and len(calls) == 1
        assert open(n3m.PID_FILE).read() == "4242"

    def test_popen_failure_removes_the_reservation(self, monkeypatch):
        monkeypatch.setattr(n3m, "_start_server", _real_start_server)
        monkeypatch.setattr(n3m, "_get_health", lambda port=None: None)
        monkeypatch.setattr(n3m, "SERVER_WAIT_SECONDS", 0)

        def boom(*a, **k):
            raise OSError("cannot spawn")

        monkeypatch.setattr(n3m.subprocess, "Popen", boom)
        assert n3m.ensure_server() is False and not os.path.exists(n3m.PID_FILE)
        calls = []
        monkeypatch.setattr(n3m.subprocess, "Popen", lambda *a, **k: calls.append(1) or self._proc(5151))
        n3m.ensure_server()
        assert calls == [1] and open(n3m.PID_FILE).read() == "5151"

    def test_the_call_that_lost_never_rewrites_the_pid_file(self, monkeypatch):
        open(n3m.PID_FILE, "w").write("777")
        t0 = time.time() - 30
        os.utime(n3m.PID_FILE, (t0, t0))
        monkeypatch.setattr(n3m, "_start_server", _real_start_server)
        monkeypatch.setattr(n3m, "_get_health", lambda port=None: None)
        monkeypatch.setattr(n3m, "_pid_is_own", lambda pid: True)
        monkeypatch.setattr(n3m, "_listen_ports", lambda pid: [])
        monkeypatch.setattr(n3m, "SERVER_WAIT_SECONDS", 0)
        monkeypatch.setattr(n3m.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launched")))
        assert n3m._start_server() is False and n3m._SERVER_STARTING is True
        assert open(n3m.PID_FILE).read() == "777" and abs(os.path.getmtime(n3m.PID_FILE) - t0) < 1

    def test_empty_pid_file_younger_than_60_s_counts_as_starting(self, monkeypatch):
        open(n3m.PID_FILE, "w").close()
        monkeypatch.setattr(n3m, "_start_server", _real_start_server)
        monkeypatch.setattr(n3m, "_get_health", lambda port=None: None)
        monkeypatch.setattr(n3m, "SERVER_WAIT_SECONDS", 0)
        monkeypatch.setattr(n3m.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launched")))
        assert n3m.ensure_server() is False and n3m._SERVER_STARTING is True and os.path.exists(n3m.PID_FILE)
        assert n3m._start_server() is False and open(n3m.PID_FILE).read() == ""
        # older than 60 s: dead, removed, and the server is started
        t0 = time.time() - 120
        os.utime(n3m.PID_FILE, (t0, t0))
        calls = []
        monkeypatch.setattr(n3m.subprocess, "Popen", lambda *a, **k: calls.append(1) or self._proc(6161))
        n3m.ensure_server()
        assert calls == [1] and open(n3m.PID_FILE).read() == "6161"


_real_start_server = n3m._start_server


class TestServerApi:
    @pytest.fixture
    def app(self, use_fake_embed):
        return n3m.create_app()

    def test_bad_host_403_everywhere(self, app):
        c = TestClient(app, base_url="http://evil.example")
        for m, path in (("get", "/health"), ("post", "/buffer"), ("post", "/search"), ("post", "/repair"),
                        ("get", "/list")):
            assert getattr(c, m)(path).status_code == 403

    def test_localhost_host_allowed(self, app):
        assert TestClient(app, base_url="http://localhost:18526").get("/health").status_code == 200

    def test_origin_header_403_even_with_good_host(self, app):
        c = TestClient(app, base_url="http://127.0.0.1:18526")
        assert c.get("/health", headers={"Origin": "http://evil.example"}).status_code == 403
        assert c.get("/health", headers={"Origin": "null"}).status_code == 403
        assert c.get("/health").status_code == 200

    def test_endpoints_are_plain_def(self, app):
        import inspect
        for r in app.routes:
            if getattr(r, "path", "") in ("/buffer", "/search", "/repair", "/list"):
                assert not inspect.iscoroutinefunction(r.endpoint)

    def test_repair_max_records(self, app, conn, cfg):
        for i in range(5):
            add(conn, cfg, f"unindexed {i}", embed=False)
        c = TestClient(app, base_url="http://127.0.0.1:18526")
        assert c.post("/repair", json={"max_records": 2}).json()["count"] == 2
        assert c.post("/repair", json={}).json()["count"] == 3

    def test_client_does_not_use_proxy_and_sends_no_origin(self, monkeypatch):
        import http.server
        import threading
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')

            def log_message(self, *a):
                pass

        real_get = n3m._http  # not the patched _get
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        proxy = http.server.HTTPServer(("127.0.0.1", 0), H)
        for s in (srv, proxy):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.server_port}")
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{proxy.server_port}")
        assert real_get("GET", "/health", port=srv.server_port) == {"status": "ok"}
        srv.shutdown()
        proxy.shutdown()
        assert len(seen) == 1 and "Origin" not in seen[0]


class TestForeignServer:
    def test_saves_go_to_own_db_directly_and_search_is_off(self, conn, monkeypatch, capsys):
        monkeypatch.setattr(n3m, "_SERVER_OK", False)
        monkeypatch.setattr(n3m, "_FOREIGN_SERVER_ROOT", "/other")
        assert n3m._save_record("[user] direct save")["status"] == "ok"
        assert db.count_memories(conn) == 1 and conn.execute("SELECT COUNT(*) FROM memories_vec").fetchone()[0] == 0
        n3m.cmd_search("direct save")
        assert "memory search unavailable: another N3MC folder's server is using port" in capsys.readouterr().out

    def test_repair_does_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(n3m, "_SERVER_OK", False)
        monkeypatch.setattr(n3m, "_FOREIGN_SERVER_ROOT", "/other")
        assert n3m.cmd_repair() == 0 and "skipped" in capsys.readouterr().err


class TestConfig:
    def test_unreadable_config_is_not_overwritten(self):
        os.makedirs(n3m.HOME_DIR, exist_ok=True)
        open(n3m.CONFIG_FILE, "w").write("{ not json")
        os.utime(n3m.CONFIG_FILE, (1, 1))
        cfg = n3m._load_config()
        assert open(n3m.CONFIG_FILE).read() == "{ not json" and cfg["server_port"] == 18526
        assert "config_unreadable" in n3m._notices_read()

    def test_bad_values_ignored_individually(self):
        n3m._load_config()
        cfg = json.load(open(n3m.CONFIG_FILE))
        cfg.update({"vector_min_cos": "0.83", "search_query_max_chars": 2000.0, "half_life_days": 0,
                    "server_port": 70000, "min_score": 1.5, "min_results": -1, "search_result_limit": 1366,
                    "pair_top_n": 5})
        open(n3m.CONFIG_FILE, "w").write(json.dumps(cfg))
        out = n3m._load_config()
        assert out["vector_min_cos"] == n3m.DEFAULT_CONFIG["vector_min_cos"] and out["search_query_max_chars"] == 2000 and out["half_life_days"] == 90
        assert out["server_port"] == 18526 and out["min_score"] == 0.2 and out["min_results"] == 3
        assert out["search_result_limit"] == 20 and out["pair_top_n"] == 5
        assert json.load(open(n3m.CONFIG_FILE))["vector_min_cos"] == "0.83"  # file not rewritten
        msg = n3m._notices_read()["config_type"]["message"]
        assert all(k in msg for k in ("vector_min_cos", "half_life_days", "search_result_limit"))

    def test_accepts_boundaries_and_fix_clears_notice(self):
        n3m._load_config()
        cfg = json.load(open(n3m.CONFIG_FILE))
        cfg.update({"min_results": 0, "search_result_limit": 1365})
        open(n3m.CONFIG_FILE, "w").write(json.dumps(cfg))
        out = n3m._load_config()
        assert out["min_results"] == 0 and out["search_result_limit"] == 1365
        assert "config_type" not in n3m._notices_read()

    def test_k_4095_vector_search_works(self, conn, cfg):
        add(conn, cfg, "a")
        assert db.search_vector(conn, fake_embed("a"), k=4095)

    def test_exclusive_create_keeps_the_winners_ids(self, monkeypatch):
        n3m._load_config()
        first = json.load(open(n3m.CONFIG_FILE))["owner_id"]
        monkeypatch.setattr(n3m, "_CFG_CACHE", None)
        assert n3m._load_config()["owner_id"] == first

    def test_ids_recovered_from_db(self, conn, cfg):
        os.unlink(n3m.CONFIG_FILE)
        add(conn, cfg, "x")
        assert n3m._load_config()["owner_id"] == cfg["owner_id"]

    def test_update_goes_through_os_replace(self, monkeypatch):
        n3m._load_config()
        cfg = json.load(open(n3m.CONFIG_FILE))
        del cfg["min_results"]
        open(n3m.CONFIG_FILE, "w").write(json.dumps(cfg))
        seen = []
        real = os.replace
        monkeypatch.setattr(os, "replace", lambda a, b: seen.append(b) or real(a, b))
        n3m._load_config()
        assert n3m.CONFIG_FILE in seen and json.load(open(n3m.CONFIG_FILE))["min_results"] == 3

    # ---- 2026-11-22, review #2: filling in the IDs of an existing file is serialized
    def test_concurrent_fill_in_ends_with_the_ids_on_disk(self, monkeypatch):
        import threading
        os.makedirs(n3m.HOME_DIR, exist_ok=True)
        open(n3m.CONFIG_FILE, "w").write(json.dumps({"min_score": 0.3, "my_own_note": "keep me"}))
        barrier, local = threading.Barrier(2), threading.local()
        real_read = n3m._read_config_file

        def read():
            out = real_read()
            if not getattr(local, "seen", False):  # both calls read the file without IDs first
                local.seen = True
                barrier.wait(10)
            return out

        monkeypatch.setattr(n3m, "_read_config_file", read)
        results = []
        ts = [threading.Thread(target=lambda: results.append(n3m._load_config())) for _ in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(30)
        disk = json.load(open(n3m.CONFIG_FILE))
        assert len(results) == 2
        for r in results:
            assert (r["owner_id"], r["local_id"]) == (disk["owner_id"], disk["local_id"])
        assert disk["min_score"] == 0.3 and disk["my_own_note"] == "keep me"
        assert not os.path.exists(os.path.join(n3m.MEMORY_DIR, "config.lock"))

    def test_stale_config_lock_is_removed(self):
        os.makedirs(n3m.HOME_DIR, exist_ok=True)
        open(n3m.CONFIG_FILE, "w").write(json.dumps({"min_score": 0.3}))
        lock = os.path.join(n3m.MEMORY_DIR, "config.lock")
        open(lock, "w").write("1")
        os.utime(lock, (time.time() - 60, time.time() - 60))
        t = time.time()
        cfg = n3m._load_config()
        assert time.time() - t < 5 and json.load(open(n3m.CONFIG_FILE))["owner_id"] == cfg["owner_id"]
        assert not os.path.exists(lock)

    # ---- 2026-11-22, review #9: the server's code_version comes from the content it loaded
    def _run_server(self, monkeypatch):
        import uvicorn
        monkeypatch.setattr(uvicorn, "run", lambda app, **k: None)
        monkeypatch.setattr(n3m._processor, "get_model", lambda name=None: object())
        monkeypatch.setattr(n3m, "_CFG_CACHE", None)
        monkeypatch.setattr(n3m, "_SERVER_STATE", {})
        assert n3m.cmd_run_server() == 0
        return {"status": "ok", "root": n3m.HOME_DIR, "code_version": n3m._SERVER_STATE["code_version"]}

    def test_server_code_version_equals_client_after_fill_in(self, monkeypatch):
        os.makedirs(n3m.HOME_DIR, exist_ok=True)
        open(n3m.CONFIG_FILE, "w").write(json.dumps({"min_score": 0.3}))  # no IDs: the server fills them in
        h = self._run_server(monkeypatch)
        assert "owner_id" in json.load(open(n3m.CONFIG_FILE))
        assert h["code_version"] == n3m.compute_code_version() and n3m._health_decision(h) == "ok"
        assert n3m._health_decision(self._run_server(monkeypatch)) == "ok"  # nothing changed: same value

    def test_change_right_after_the_server_read_makes_it_stale(self, monkeypatch):
        n3m._load_config()
        real_read = n3m._read_config_file

        def read_then_edit():
            out = real_read()
            d = json.load(open(n3m.CONFIG_FILE))
            d["min_score"] = 0.35
            open(n3m.CONFIG_FILE, "w").write(json.dumps(d))
            return out

        monkeypatch.setattr(n3m, "_read_config_file", read_then_edit)
        h = self._run_server(monkeypatch)
        assert n3m._SERVER_STATE["cfg"]["min_score"] == 0.2 and n3m._health_decision(h) == "stale"
        monkeypatch.setattr(n3m, "_read_config_file", real_read)
        h = self._run_server(monkeypatch)  # the restart
        assert n3m._SERVER_STATE["cfg"]["min_score"] == 0.35 and n3m._health_decision(h) == "ok"


class TestPurifyBeforeChunk:
    def test_text_between_two_code_blocks_survives(self, conn):
        text = "intro " * 20 + "\n```\n" + "code1\n" * 20 + "```\n" + "middle sentence stays. " * 12 + \
               "\n```\n" + "code2\n" * 20 + "```\n" + "outro"
        assert len(text) > 500
        n3m._save_text("user", text, "T")
        stored = " ".join(r[0] for r in conn.execute("SELECT content FROM memories"))
        assert "middle sentence stays." in stored and "code1" not in stored and "code2" not in stored

    def test_long_code_block_not_stored(self, conn):
        n3m._save_text("user", "before\n```\n" + "x = 1\n" * 200 + "```\nafter", "T")
        stored = " ".join(r[0] for r in conn.execute("SELECT content FROM memories"))
        assert "x = 1" not in stored and "[code omitted]" in stored


class TestChunkSentences:
    def test_japanese_text_splits_after_sentence_ends(self):
        text = "".join(f"これは{i}番目の文章です。" for i in range(80))
        chunks = p.chunk_text(text)
        assert len(chunks) > 1 and all(len(c) <= 400 for c in chunks)
        assert chunks[0].endswith("。")  # cut after a sentence end, not in the middle of a sentence


class TestTimeBounds:
    def test_date_only_since_is_local_midnight_in_utc(self):
        want = datetime(2026, 11, 13).astimezone(timezone.utc).isoformat()
        assert n3m._parse_time_bound("2026-11-13") == want

    def test_until_is_end_of_day(self):
        want = datetime(2026, 11, 13, 23, 59, 59, 999999).astimezone(timezone.utc).isoformat()
        assert n3m._parse_time_bound("2026-11-13", upper=True) == want

    def test_offset_is_kept(self):
        assert n3m._parse_time_bound("2026-11-13T09:00+09:00") == "2026-11-13T00:00:00+00:00"
        assert n3m._parse_time_bound("2026-11-13T00:00:00Z") == "2026-11-13T00:00:00+00:00"

    def test_t_and_space_same(self):
        assert n3m._parse_time_bound("2026-11-13T09:00") == n3m._parse_time_bound("2026-11-13 09:00")

    def test_garbage_exits_2_with_one_line(self, capsys):
        assert n3m.cmd_search("x", since="yesterday") == 2
        assert "--since: cannot read 'yesterday' (use 2026-11-13 or 2026-11-13T09:00)" in capsys.readouterr().err
        assert n3m.cmd_list(until="2026-13-01") == 2
        assert "--until: cannot read '2026-13-01'" in capsys.readouterr().err
        assert n3m.cmd_list(since="2026-12-01", until="2026-11-01") == 2


class TestDbCorrupt:
    def _make_db(self):
        c = n3m._open_db()
        c.execute("INSERT INTO memories(id, content, timestamp, owner_id) VALUES ('1','x','t','o')")
        c.commit()
        c.close()

    def test_garbage_file_is_set_aside_and_noticed(self):
        open(n3m.DB_PATH, "wb").write(b"this is not a sqlite database" * 100)
        c = n3m._open_db("integrity_check")
        assert db.count_memories(c) == 0
        c.close()
        baks = [f for f in os.listdir(n3m.MEMORY_DIR) if ".corrupt-" in f and f.endswith(".bak")]
        assert len(baks) == 1 and "db_corrupt" in n3m._notices_read()

    def test_second_corruption_keeps_both_backups_and_wal_moves(self):
        for _ in range(2):
            for ext, data in (("", b"junk"), ("-wal", b"wal"), ("-shm", b"shm")):
                open(n3m.DB_PATH + ext, "wb").write(data)
            n3m._quarantine_db()
        names = os.listdir(n3m.MEMORY_DIR)
        baks = sorted(f for f in names if ".corrupt-" in f and f.endswith(".bak"))
        assert len(baks) == 2 and baks[0].endswith("-2.bak") or baks[1].endswith("-2.bak")
        assert len([f for f in names if f.endswith(".bak-wal")]) == 2 and len([f for f in names if f.endswith(".bak-shm")]) == 2
        assert not os.path.exists(n3m.DB_PATH + "-wal")

    def test_quick_check_once_per_process(self, monkeypatch):
        seen = []
        real = n3m._connect_checked
        monkeypatch.setattr(n3m, "_connect_checked", lambda pragma=None: seen.append(pragma) or real(pragma))
        for _ in range(3):
            n3m._open_db_direct().close()
        assert seen == ["quick_check", None, None]

    def test_operational_error_is_not_corruption(self):
        assert not n3m._is_corruption_error(sqlite3.OperationalError("database is locked"))
        assert not n3m._is_corruption_error(RuntimeError("sqlite-vec ... Recovery: pip install sqlite-vec"))
        assert n3m._is_corruption_error(sqlite3.DatabaseError("file is not a database"))
        assert n3m._is_corruption_error(sqlite3.DatabaseError("database disk image is malformed"))

    def test_direct_save_after_corruption_works(self):
        open(n3m.DB_PATH, "wb").write(b"junk" * 1000)
        assert n3m._buffer_direct("[user] after corruption")["status"] == "ok"


class TestSaveFailedNotice:
    """A save through the server that ends ok / skipped clears save_failed (2026-11-22, F2)."""

    def _keys(self):
        if not os.path.exists(n3m.NOTICES_FILE):
            return set()
        return set(json.load(open(n3m.NOTICES_FILE, encoding="utf-8")))

    @pytest.mark.parametrize("status", ["ok", "skipped"])
    def test_server_save_clears_save_failed(self, monkeypatch, status):
        n3m._notify("save_failed", "A record could not be saved (test).")
        assert "save_failed" in self._keys()
        monkeypatch.setattr(n3m, "_use_server", lambda: True)
        monkeypatch.setattr(n3m, "_post", lambda path, body, *a, **k: {"status": status, "count": 1})
        assert n3m._save_record("[user] hello", turn_id="T1")["status"] == status
        assert "save_failed" not in self._keys()


class TestModelRetry:
    def test_no_retry_for_60_seconds_after_a_failure(self, monkeypatch):
        monkeypatch.setattr(p, "_model", None)
        monkeypatch.setattr(p, "_model_failed_at", None)
        calls = []
        monkeypatch.setattr(p, "_load_model", lambda name: calls.append(name) or (_ for _ in ()).throw(OSError("offline")))
        for _ in range(3):
            with pytest.raises(Exception):
                p.get_model("some/model")
        assert len(calls) == 1

    def test_env_var_has_no_effect(self, monkeypatch):
        monkeypatch.setenv("N3MC_EMBED_MODEL", "other/model")
        assert n3m.get_config()["embed_model"] == "intfloat/multilingual-e5-base"


class TestPackaging:
    def test_psutil_is_a_dependency(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        deps = tomllib.load(open(os.path.join(root, "pyproject.toml"), "rb"))["project"]["dependencies"]
        assert any(d.startswith("psutil") for d in deps)


class TestWeakMatches:
    def test_fills_up_to_min_results_in_filter_score_order(self, conn, cfg):
        add(conn, cfg, "zebra stripes quagga")
        add(conn, cfg, "zebra mammals africa savanna")
        add(conn, cfg, "zebra crossing street sign")
        add(conn, cfg, "unrelated pottery wheel clay")
        res = search(conn, cfg, "zebra stripes quagga")["results"]
        normal = [r for r in res if not r["weak"]]
        weak = [r for r in res if r["weak"]]
        assert len(normal) == 1 and len(res) == 3 and res.index(weak[0]) > res.index(normal[-1])
        assert weak == sorted(weak, key=lambda r: r["filter_score"], reverse=True)

    def test_min_results_zero_adds_nothing(self, conn, cfg):
        add(conn, cfg, "zebra stripes quagga")
        add(conn, cfg, "zebra mammals africa savanna")
        res = search(conn, {**cfg, "min_results": 0}, "zebra stripes quagga")["results"]
        assert all(not r["weak"] for r in res) and len(res) == 1

    def test_limit_smaller_than_min_results(self, conn, cfg):
        for i in range(4):
            add(conn, cfg, f"zebra variant text {i} with words")
        res = search(conn, {**cfg, "search_result_limit": 2}, "zebra variant text 0 with words")["results"]
        assert len(res) <= 2

    def test_same_content_skipped(self, conn, cfg):
        add(conn, cfg, "zebra stripes quagga", turn_id="a", ts=ago(2))
        add(conn, cfg, "zebra stripes quagga", turn_id="b", ts=ago(1))
        res = search(conn, cfg, "zebra stripes quagga")["results"]
        assert len([r for r in res if r["content"] == "zebra stripes quagga"]) == 1

    def test_per_turn_cap_applies_to_weak(self, conn, cfg):
        add(conn, cfg, "zebra stripes quagga", turn_id="T")
        for i in range(3):
            add(conn, cfg, f"zebra mammals africa savanna {i}", turn_id="T")
        res = search(conn, cfg, "zebra stripes quagga")["results"]
        assert len([r for r in res if r["turn_id"] == "T"]) <= 2

    def test_orthogonal_vectors_not_added(self, conn, cfg):
        add(conn, cfg, "pottery wheel clay")
        res = search(conn, cfg, "completely different astronomy words")["results"]
        assert all(r["filter_score"] >= 1e-6 for r in res)

    def test_weak_do_not_feed_pairs(self, conn, cfg):
        add(conn, cfg, "[user] pottery wheel clay", turn_id="W")
        res = search(conn, cfg, "pottery")
        assert "W" not in res["pairs"] or not any(r["weak"] and r["turn_id"] == "W" for r in res["results"])

    def test_empty_query_returns_nothing(self, conn, cfg):
        add(conn, cfg, "something")
        assert search(conn, cfg, "")["results"] == []


class TestPidFileRemoval:
    def test_own_pid_file_is_deleted_and_a_foreign_one_is_kept(self):
        open(n3m.PID_FILE, "w").write(str(os.getpid()))
        n3m._remove_own_pid_file()
        assert not os.path.exists(n3m.PID_FILE)  # (an open handle would make this fail on Windows)
        open(n3m.PID_FILE, "w").write("999999")
        n3m._remove_own_pid_file()
        assert os.path.exists(n3m.PID_FILE)

    def test_exit_server_removes_the_pid_file(self, monkeypatch):
        open(n3m.PID_FILE, "w").write(str(os.getpid()))
        monkeypatch.setattr(n3m._os, "_exit", lambda code: None)
        n3m._exit_server()
        assert not os.path.exists(n3m.PID_FILE)


def _vec_at(cos, axis=1):
    """A unit vector whose cosine with e0 is `cos` (the rest goes on another axis)."""
    v = [0.0] * 768
    v[0] = cos
    v[axis] = (1 - cos * cos) ** 0.5
    return v


def _e0(_text):
    v = [0.0] * 768
    v[0] = 1.0
    return v


def _add_vec(conn, cfg, content, cos, axis=1, turn_id=None):
    rid = n3m._new_id()
    db.insert_memory(conn, rid, content, NOW.isoformat(), cfg["owner_id"], cfg["local_id"], "claude-code",
                     None, turn_id=turn_id, embedding=_vec_at(cos, axis))
    return rid
