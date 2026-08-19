from src.backup import BackupManager


def test_create_backup_returns_none_when_source_missing(tmp_path):
    manager = BackupManager(tmp_path)

    result = manager.create_backup(tmp_path / "missing.txt")

    assert result is None


def test_create_backup_copies_file_and_records_metadata(tmp_path):
    source = tmp_path / "rec.txt"
    source.write_text("a.png\tтекст\n", encoding="utf-8")
    manager = BackupManager(tmp_path)

    backup_path = manager.create_backup(source, operation="save")

    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.read_text(encoding="utf-8") == "a.png\tтекст\n"

    backups = manager.get_backups_list()
    assert len(backups) == 1
    assert backups[0]["operation"] == "save"
    assert backups[0]["original"] == "rec.txt"


def test_rotation_keeps_only_max_backups(tmp_path):
    source = tmp_path / "rec.txt"
    manager = BackupManager(tmp_path, max_backups=2)

    for i in range(4):
        source.write_text(f"version {i}\n", encoding="utf-8")
        manager.create_backup(source)

    backups = manager.get_backups_list()
    assert len(backups) == 2


def test_restore_backup_copies_content_back(tmp_path):
    source = tmp_path / "rec.txt"
    source.write_text("original\n", encoding="utf-8")
    manager = BackupManager(tmp_path)
    backup_path = manager.create_backup(source)

    source.write_text("changed\n", encoding="utf-8")
    ok = manager.restore_backup(backup_path.name, source)

    assert ok is True
    assert source.read_text(encoding="utf-8") == "original\n"


def test_restore_backup_returns_false_for_unknown_name(tmp_path):
    manager = BackupManager(tmp_path)

    ok = manager.restore_backup("does_not_exist.backup.txt", tmp_path / "rec.txt")

    assert ok is False


def test_get_backups_list_sorted_newest_first(tmp_path):
    manager = BackupManager(tmp_path)
    manager.metadata["backups"] = [
        {"file": "a", "timestamp": "20240101_000000", "operation": "save", "original": "rec.txt"},
        {"file": "b", "timestamp": "20240102_000000", "operation": "save", "original": "rec.txt"},
    ]

    backups = manager.get_backups_list()

    assert [b["file"] for b in backups] == ["b", "a"]
