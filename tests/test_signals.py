"""Signal watching matches keywords and falls back cleanly."""
from app import signals


def test_local_file_matches_keywords(tmp_path, monkeypatch):
    feed = tmp_path / "signals.txt"
    feed.write_text("Acme is hiring a CISO\nBeta raised a seed round\nplain noise\n",
                    encoding="utf-8")
    monkeypatch.setenv("CORP_SIGNALS_FILE", str(feed))
    monkeypatch.setenv("CORP_SIGNAL_SOURCES", "local")
    hits = signals.find_signals(["ciso", "raised"], 5)
    assert len(hits) == 2


def test_empty_without_any_source(monkeypatch):
    monkeypatch.delenv("CORP_SIGNALS_FILE", raising=False)
    monkeypatch.delenv("CORP_SIGNALS_URL", raising=False)
    monkeypatch.setenv("CORP_SIGNAL_SOURCES", "browser,local")
    assert signals.find_signals(["x"], 3) == []
