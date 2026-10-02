from pathlib import Path

def test_backup_verification_script_exists():
    path=Path(__file__).parents[1]/"scripts"/"verify_backup.sh"
    assert path.exists()
    content=path.read_text()
    assert "pg_restore --list" in content
    assert "BACKUP_MAX_AGE_SECONDS" in content
