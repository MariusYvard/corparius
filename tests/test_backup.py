"""A backup that quietly omits the store, or that carries a deleted company
forward, is worse than no backup: the operator finds out at restore time.

The warning matters as much as the archive. This design created the fact that a
backup zip holds the console's API keys in the clear, so `describe()` is the one
place that has to keep saying so.
"""

import zipfile

from corparius import backup


def _tree(tmp_path):
    """A writable home shaped like a real install: data/ next to companies/."""
    data = tmp_path / "data"
    data.mkdir()
    (data / "corparius.sqlite").write_text("db", encoding="utf-8")
    companies = tmp_path / "companies"
    (companies / "acme").mkdir(parents=True)
    (companies / "acme" / "company.yaml").write_text("slug: acme", encoding="utf-8")
    (companies / ".trash" / "gone").mkdir(parents=True)
    (companies / ".trash" / "gone" / "company.yaml").write_text("slug: gone", encoding="utf-8")
    return data


def _names(path):
    with zipfile.ZipFile(path) as zf:
        return {n.replace("\\", "/") for n in zf.namelist()}


def test_backup_carries_the_store_and_the_companies(tmp_path, monkeypatch):
    data = _tree(tmp_path)
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    names = _names(backup.make_backup(str(data), out_dir=str(tmp_path / "out")))
    assert "data/corparius.sqlite" in names
    assert "companies/acme/company.yaml" in names


def test_deleted_companies_are_not_carried_forward(tmp_path, monkeypatch):
    """companies/.trash is where a deleted company goes instead of being erased;
    restoring a backup must not resurrect it."""
    data = _tree(tmp_path)
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    names = _names(backup.make_backup(str(data), out_dir=str(tmp_path / "out")))
    assert not any(".trash" in n for n in names)


def test_a_data_dir_outside_the_home_is_still_archived(tmp_path, monkeypatch):
    """CORP_DATA_PATH can point anywhere, so relative_to(ROOT) raises and the
    walk falls back to the directory's own name. Without that branch the store
    would be dropped from the archive without a word."""
    monkeypatch.setattr(backup, "ROOT", tmp_path / "home")
    (tmp_path / "home").mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "corparius.sqlite").write_text("db", encoding="utf-8")
    names = _names(backup.make_backup(str(outside), out_dir=str(tmp_path / "out")))
    assert "elsewhere/corparius.sqlite" in names


def test_missing_directories_are_skipped_not_fatal(tmp_path, monkeypatch):
    """First run backs up before any company exists."""
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    path = backup.make_backup(str(tmp_path / "absent"), out_dir=str(tmp_path / "out"))
    assert path.is_file()


def test_the_stamp_names_the_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    path = backup.make_backup(
        str(_tree(tmp_path)), out_dir=str(tmp_path / "out"), stamp="20260720-101500"
    )
    assert path.name == "corparius-backup-20260720-101500.zip"


def test_describe_warns_about_the_keys_in_both_languages(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "ROOT", tmp_path)
    path = backup.make_backup(str(_tree(tmp_path)), out_dir=str(tmp_path / "out"))
    assert backup.WARNING_EN in backup.describe(path)
    assert backup.WARNING_FR in backup.describe(path, "fr")
    assert path.name in backup.describe(path)
