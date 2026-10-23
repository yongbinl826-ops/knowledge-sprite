"""Synthetic operator backup checks; never opens any real project/config DB."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from scripts.backup_mobile_public import APPLICATION_ID, MARKER, backup_public


class PublicBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "public.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def make_public(self, version=1):
        db = sqlite3.connect(self.source)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.executescript("""
            CREATE TABLE mobile_metadata(schema_version INTEGER);
            CREATE TABLE mobile_public_courses(course_id TEXT, platform TEXT, title TEXT, observed REAL, expires REAL, data TEXT);
            CREATE TABLE mobile_daily_budget(day TEXT, tasks INTEGER, analysis_calls INTEGER, model_calls INTEGER, search_requests INTEGER, detail_pages INTEGER, detail_http INTEGER);
            INSERT INTO mobile_public_courses VALUES('public_test', 'bilibili', 'Public Python video', 1, 2, '{}');
            INSERT INTO mobile_daily_budget VALUES('2026-10-20', 7, 3, 19, 20, 10, 400);
        """)
        db.execute("INSERT INTO mobile_metadata VALUES(?)", (version,))
        db.commit()
        self.source.with_name(self.source.name + ".mobile-public").write_bytes(MARKER)
        return db

    def test_wal_consistent_copy_keeps_budget_and_can_reopen(self):
        db = self.make_public()
        db.execute("UPDATE mobile_daily_budget SET model_calls=23")
        db.commit()
        target = self.root / "backup.sqlite3"
        result = backup_public(self.source, target)
        self.assertEqual(result["status"], "backed_up")
        with closing(sqlite3.connect(target)) as restored:
            self.assertEqual(restored.execute("SELECT model_calls FROM mobile_daily_budget").fetchone(), (23,))
            self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone(), ("ok",))
        self.assertEqual(target.with_name(target.name + ".mobile-public").read_bytes(), MARKER)
        db.close()

    def test_unknown_legacy_file_not_even_opened(self):
        self.source.write_bytes(b"synthetic legacy sentinel")
        with patch("scripts.backup_mobile_public.sqlite3.connect", side_effect=AssertionError("must not open")):
            with self.assertRaises(ValueError):
                backup_public(self.source, self.root / "backup.sqlite3")
        self.assertEqual(self.source.read_bytes(), b"synthetic legacy sentinel")

    def test_existing_target_is_never_overwritten(self):
        self.make_public().close()
        target = self.root / "old.sqlite3"
        target.write_bytes(b"keep me")
        with self.assertRaises(FileExistsError):
            backup_public(self.source, target)
        self.assertEqual(target.read_bytes(), b"keep me")

    def test_unknown_version_refused_before_destination_creation(self):
        self.make_public(version=2).close()
        target = self.root / "backup.sqlite3"
        with self.assertRaises(ValueError):
            backup_public(self.source, target)
        self.assertFalse(target.exists())

    def test_extra_personal_table_refused(self):
        db = self.make_public()
        db.execute("CREATE TABLE projects(secret TEXT)")
        db.commit()
        db.close()
        with self.assertRaises(ValueError):
            backup_public(self.source, self.root / "backup.sqlite3")


if __name__ == "__main__":
    unittest.main()
