"""The deliverability guard must block suppressed addresses and honour the cap."""

from corparius import deliverability


def test_allows_by_default(monkeypatch):
    monkeypatch.delenv("CORP_SUPPRESSION_FILE", raising=False)
    monkeypatch.delenv("CORP_OUTREACH_DAILY_CAP", raising=False)
    assert deliverability.can_send("a@x.com")[0] is True


def test_suppression_list_blocks(monkeypatch, tmp_path):
    supp = tmp_path / "supp.txt"
    supp.write_text("blocked@x.com\n", encoding="utf-8")
    monkeypatch.setenv("CORP_SUPPRESSION_FILE", str(supp))
    ok, reason = deliverability.can_send("blocked@x.com")
    assert ok is False and "suppression" in reason


def test_daily_cap_blocks_after_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("CORP_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("CORP_OUTREACH_DAILY_CAP", "1")
    monkeypatch.delenv("CORP_SUPPRESSION_FILE", raising=False)
    assert deliverability.can_send("a@x.com")[0] is True
    deliverability.record_send()
    assert deliverability.can_send("a@x.com")[0] is False
