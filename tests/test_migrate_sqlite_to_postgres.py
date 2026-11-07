"""Tests for scripts/migrate_sqlite_to_postgres.py (fake data only).

Every test runs against a throw-away SQLite target. When TEST_DATABASE_URL
points at a PostgreSQL test database, the same tests also run against it.
"""

import hashlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import Base
from app.database.session import normalize_database_url
from app.models import (
    AdminAuditLog,
    BloodPressureReading,
    ChatConversation,
    ChatMessage,
    GlucoseReading,
    ReadingType,
    User,
)
from scripts import migrate_sqlite_to_postgres as migration

pytestmark = pytest.mark.filterwarnings("ignore::sqlalchemy.exc.SAWarning")

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

# A made-up stand-in for a password hash. It must be copied exactly as it is.
HASH_ADMIN = "$argon2id$v=19$m=65536,t=3,p=4$FAKEsaltAAAA$FAKEhashAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
HASH_USER = "$argon2id$v=19$m=65536,t=3,p=4$FAKEsaltBBBB$FAKEhashBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"

TABLES = [table.name for table in Base.metadata.sorted_tables]
WHEN = datetime(2026, 3, 1, 8, 30, 15, 123456, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _postgres_engine():
    url = make_url(normalize_database_url(TEST_DATABASE_URL))
    if "test" not in (url.database or "").lower():
        raise RuntimeError("TEST_DATABASE_URL must name a database containing 'test'.")
    return create_engine(url)


@pytest.fixture(params=["sqlite", "postgres"])
def target_engine(request, tmp_path):
    """An empty target database with all tables created."""
    if request.param == "postgres":
        if not TEST_DATABASE_URL:
            pytest.skip("set TEST_DATABASE_URL to run against PostgreSQL")
        engine = _postgres_engine()
        Base.metadata.drop_all(bind=engine)
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    Base.metadata.create_all(bind=engine)
    yield engine
    if request.param == "postgres":
        Base.metadata.drop_all(bind=engine)
    engine.dispose()


def seed_source(path):
    """A small SQLite file like the app would have made, with explicit ids."""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        db.add_all(
            [
                User(id=1, full_name="Alice Admin", email="alice@example.com",
                     hashed_password=HASH_ADMIN, role="admin", created_at=WHEN),
                User(id=2, full_name="Bob Basic", email="bob@example.com",
                     hashed_password=HASH_USER, role="user", is_active=False,
                     created_at=WHEN + timedelta(days=1)),
                # Gaps in the ids on purpose (users were deleted over time).
                User(id=5, full_name="Cara Cole", email="cara@example.com",
                     hashed_password=HASH_USER, role="user",
                     created_at=WHEN + timedelta(days=2)),
            ]
        )
        db.flush()
        db.add_all(
            [
                GlucoseReading(id=10, user_id=2, glucose_value=Decimal("95.50"),
                               reading_type=ReadingType.FASTING, recorded_at=WHEN,
                               notes="fake note"),
                GlucoseReading(id=11, user_id=2, glucose_value=Decimal("140.25"),
                               reading_type=ReadingType.AFTER_MEAL,
                               recorded_at=WHEN + timedelta(hours=3), notes=None),
                GlucoseReading(id=12, user_id=5, glucose_value=Decimal("101.00"),
                               reading_type=ReadingType.BEFORE_MEAL, recorded_at=WHEN),
                BloodPressureReading(id=20, user_id=2, systolic=120, diastolic=80,
                                     pulse=70, recorded_at=WHEN, notes="fake"),
                BloodPressureReading(id=21, user_id=5, systolic=135, diastolic=85,
                                     pulse=None, recorded_at=WHEN),
                ChatConversation(id=30, user_id=5, title="Fake chat", created_at=WHEN),
            ]
        )
        db.flush()
        db.add_all(
            [
                ChatMessage(id=40, conversation_id=30, role="user",
                            content="Fake question", created_at=WHEN),
                ChatMessage(id=41, conversation_id=30, role="assistant",
                            content="Fake answer", created_at=WHEN + timedelta(seconds=2)),
                AdminAuditLog(id=50, admin_user_id=1, target_user_id=2,
                              action="admin_promoted", detail="user -> admin",
                              created_at=WHEN),
            ]
        )
        db.commit()
    engine.dispose()
    return path


@pytest.fixture
def source_file(tmp_path):
    return seed_source(tmp_path / "meditrack.db")


@pytest.fixture
def source(source_file):
    engine = migration.open_sqlite_readonly(source_file)
    yield engine
    engine.dispose()


def counts(engine):
    with engine.connect() as connection:
        return {
            name: connection.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one()
            for name in TABLES
        }


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quiet(*_args, **_kwargs):
    return None


# ---------------------------------------------------------------------------
# The copy itself
# ---------------------------------------------------------------------------


def test_rehearsal_writes_nothing(source, target_engine):
    report = migration.migrate(source, target_engine, execute=False, log=quiet)

    assert report.committed is False
    assert report.total_rows == 3 + 3 + 2 + 1 + 2 + 1
    assert set(counts(target_engine).values()) == {0}


def test_execute_copies_every_table(source, target_engine):
    report = migration.migrate(source, target_engine, execute=True, log=quiet)

    assert report.committed is True
    assert counts(target_engine) == {
        "users": 3,
        "glucose_readings": 3,
        "blood_pressure_readings": 2,
        "chat_conversations": 1,
        "chat_messages": 2,
        "admin_audit_log": 1,
    }


def test_accounts_hashes_roles_and_ids_are_kept_exactly(source, target_engine):
    migration.migrate(source, target_engine, execute=True, log=quiet)

    with Session(target_engine) as db:
        users = {u.id: u for u in db.scalars(select(User))}
    assert sorted(users) == [1, 2, 5]  # ids are kept, gaps included
    assert users[1].hashed_password == HASH_ADMIN  # copied, never re-hashed
    assert users[2].hashed_password == HASH_USER
    assert users[1].role == "admin"  # administrator rights survive
    assert users[2].role == "user"
    assert users[2].is_active is False
    assert users[1].email == "alice@example.com"
    created = users[1].created_at
    if created.tzinfo is None:  # SQLite targets hand back times without a zone
        created = created.replace(tzinfo=timezone.utc)
    assert created == WHEN


def test_readings_and_relationships_are_kept(source, target_engine):
    migration.migrate(source, target_engine, execute=True, log=quiet)

    with Session(target_engine) as db:
        glucose = {g.id: g for g in db.scalars(select(GlucoseReading))}
        pressure = {p.id: p for p in db.scalars(select(BloodPressureReading))}
        messages = list(db.scalars(select(ChatMessage).order_by(ChatMessage.id)))
        audit = db.get(AdminAuditLog, 50)

    assert glucose[10].glucose_value == Decimal("95.50")
    assert glucose[11].glucose_value == Decimal("140.25")
    assert glucose[10].user_id == 2 and glucose[12].user_id == 5
    assert glucose[10].reading_type == ReadingType.FASTING
    assert glucose[11].reading_type == ReadingType.AFTER_MEAL
    assert glucose[10].notes == "fake note" and glucose[11].notes is None
    assert (pressure[20].systolic, pressure[20].diastolic, pressure[20].pulse) == (120, 80, 70)
    assert pressure[21].pulse is None
    assert [m.content for m in messages] == ["Fake question", "Fake answer"]
    assert all(m.conversation_id == 30 for m in messages)
    assert (audit.admin_user_id, audit.target_user_id, audit.action) == (1, 2, "admin_promoted")


def test_the_sqlite_file_is_never_modified(source_file, target_engine):
    before = sha256(source_file)
    engine = migration.open_sqlite_readonly(source_file)
    try:
        migration.migrate(engine, target_engine, execute=True, log=quiet)

        # The connection really is read-only, not just unused.
        with pytest.raises(OperationalError):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM users"))
    finally:
        engine.dispose()
    assert sha256(source_file) == before


def test_new_rows_continue_after_the_copied_ids(source, target_engine):
    if target_engine.dialect.name != "postgresql":
        pytest.skip("id counters (sequences) only exist in PostgreSQL")
    migration.migrate(source, target_engine, execute=True, log=quiet)

    with Session(target_engine) as db:
        newcomer = User(full_name="New Person", email="new@example.com", hashed_password="x")
        reading = GlucoseReading(
            user=newcomer, glucose_value=Decimal("99.00"), reading_type=ReadingType.FASTING
        )
        db.add_all([newcomer, reading])
        db.commit()
        assert newcomer.id == 6  # highest copied id was 5
        assert reading.id == 13  # highest copied reading id was 12


# ---------------------------------------------------------------------------
# Refusals: nothing may be overwritten, merged or half-copied
# ---------------------------------------------------------------------------


def test_refuses_a_target_that_already_has_data(source, target_engine):
    with Session(target_engine) as db:
        db.add(User(full_name="Existing", email="existing@example.com", hashed_password="x"))
        db.commit()
    before = counts(target_engine)

    with pytest.raises(migration.MigrationError, match="not empty"):
        migration.migrate(source, target_engine, execute=True, log=quiet)

    assert counts(target_engine) == before


def test_refuses_a_target_without_tables_unless_asked_to_create_them(source, target_engine):
    Base.metadata.drop_all(bind=target_engine)

    with pytest.raises(migration.MigrationError, match="do not exist"):
        migration.migrate(source, target_engine, execute=True, log=quiet)

    report = migration.migrate(
        source, target_engine, execute=True, create_tables=True, log=quiet
    )
    assert report.committed is True
    assert counts(target_engine)["users"] == 3


def test_a_rehearsal_that_creates_tables_leaves_no_trace_in_postgresql(source, target_engine):
    if target_engine.dialect.name != "postgresql":
        pytest.skip("table creation can only be undone in PostgreSQL")
    Base.metadata.drop_all(bind=target_engine)

    migration.migrate(source, target_engine, execute=False, create_tables=True, log=quiet)

    with target_engine.connect() as connection:
        found = connection.execute(
            text("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'users'")
        ).scalar_one()
    assert found == 0


def test_broken_relationships_stop_everything(source_file, target_engine):
    raw = sqlite3.connect(source_file)  # foreign keys are not enforced here
    raw.execute(
        "INSERT INTO glucose_readings (id, user_id, glucose_value, reading_type, recorded_at) "
        "VALUES (99, 12345, 100, 'fasting', '2026-03-01 08:00:00.000000')"
    )
    raw.commit()
    raw.close()
    engine = migration.open_sqlite_readonly(source_file)

    try:
        with pytest.raises(migration.MigrationError, match="broken relationships"):
            migration.migrate(engine, target_engine, execute=True, log=quiet)
    finally:
        engine.dispose()
    assert set(counts(target_engine).values()) == {0}


def test_audit_references_to_deleted_users_become_empty(source_file, target_engine):
    raw = sqlite3.connect(source_file)
    raw.execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, target_user_id, action, created_at) "
        "VALUES (60, 1, 999, 'role_changed', '2026-03-01 08:00:00.000000')"
    )
    raw.commit()
    raw.close()
    engine = migration.open_sqlite_readonly(source_file)

    try:
        report = migration.migrate(engine, target_engine, execute=True, log=quiet)
    finally:
        engine.dispose()

    with Session(target_engine) as db:
        entry = db.get(AdminAuditLog, 60)
    assert entry.target_user_id is None
    assert entry.admin_user_id == 1
    assert {t.name: t.cleaned_references for t in report.tables}["admin_audit_log"] == 1


def test_a_file_that_is_not_a_meditrack_database_is_refused(tmp_path, target_engine):
    other = tmp_path / "other.db"
    raw = sqlite3.connect(other)
    raw.execute("CREATE TABLE something_else (id INTEGER)")
    raw.commit()
    raw.close()
    engine = migration.open_sqlite_readonly(other)
    try:
        with pytest.raises(migration.MigrationError, match="no 'users' table"):
            migration.migrate(engine, target_engine, execute=True, log=quiet)
    finally:
        engine.dispose()


def test_a_missing_file_is_reported_not_created(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(migration.MigrationError, match="not found"):
        migration.open_sqlite_readonly(missing)
    assert not missing.exists()


def test_an_older_database_without_role_or_chat_tables(tmp_path, target_engine):
    """A database from before the admin and chat features existed."""
    old = tmp_path / "old.db"
    raw = sqlite3.connect(old)
    raw.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, full_name VARCHAR(200) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE, hashed_password VARCHAR(255) NOT NULL,
            created_at DATETIME NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1);
        INSERT INTO users VALUES
            (1, 'Old Person', 'old@example.com', 'HASH-OLD', '2026-01-01 10:00:00.000000', 1);
        """
    )
    raw.commit()
    raw.close()
    engine = migration.open_sqlite_readonly(old)
    try:
        migration.migrate(engine, target_engine, execute=True, log=quiet)
    finally:
        engine.dispose()

    with Session(target_engine) as db:
        user = db.scalar(select(User))
    assert user.email == "old@example.com"
    assert user.hashed_password == "HASH-OLD"
    assert user.role == "user"  # the missing column gets its normal default
    assert counts(target_engine)["chat_messages"] == 0


def test_a_copy_that_differs_from_the_source_is_caught_and_undone(source, target_engine):
    """The row-by-row check: if the database changes data while saving it, stop."""
    if target_engine.dialect.name != "sqlite":
        pytest.skip("this check plants a SQLite trigger in the target")
    with target_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER tamper AFTER INSERT ON glucose_readings "
                "BEGIN UPDATE glucose_readings SET notes = 'tampered' WHERE id = NEW.id; END"
            )
        )

    with pytest.raises(migration.MigrationError, match="differs from the source"):
        migration.migrate(source, target_engine, execute=True, log=quiet)

    assert set(counts(target_engine).values()) == {0}  # nothing was saved


# ---------------------------------------------------------------------------
# The backup hook: only when the copy is really about to be written
# ---------------------------------------------------------------------------


def test_the_backup_step_runs_once_and_before_any_row_is_written(source, target_engine):
    seen = []

    def backup():
        seen.append(counts(target_engine))

    migration.migrate(source, target_engine, execute=True, before_write=backup, log=quiet)

    assert len(seen) == 1
    assert set(seen[0].values()) == {0}  # called before the first row was saved


def test_no_backup_for_a_rehearsal(source, target_engine):
    calls = []
    migration.migrate(source, target_engine, execute=False, before_write=lambda: calls.append(1), log=quiet)
    assert calls == []


def test_no_backup_when_the_run_is_refused(source, target_engine):
    calls = []
    with Session(target_engine) as db:
        db.add(User(full_name="Existing", email="existing@example.com", hashed_password="x"))
        db.commit()
    with pytest.raises(migration.MigrationError):
        migration.migrate(source, target_engine, execute=True, before_write=lambda: calls.append(1), log=quiet)
    assert calls == []

    Base.metadata.drop_all(bind=target_engine)  # tables missing is a refusal too
    with pytest.raises(migration.MigrationError):
        migration.migrate(source, target_engine, execute=True, before_write=lambda: calls.append(1), log=quiet)
    assert calls == []


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def test_two_backups_never_overwrite_each_other(source_file):
    first = migration.make_backup(source_file)
    second = migration.make_backup(source_file)
    assert first != second
    assert first.exists() and second.exists()


def test_backup_is_a_complete_copy_next_to_the_original(source_file):
    backup = migration.make_backup(source_file)

    assert backup.parent == source_file.parent
    assert backup.name.startswith("meditrack-backup-") and backup.suffix == ".db"
    assert backup != source_file
    copy = sqlite3.connect(backup)
    try:
        assert copy.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
        assert copy.execute("SELECT COUNT(*) FROM glucose_readings").fetchone()[0] == 3
    finally:
        copy.close()


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def test_cli_needs_a_target_address(source_file, monkeypatch, capsys):
    monkeypatch.delenv("TARGET_DATABASE_URL", raising=False)
    assert migration.main(["--source", str(source_file)]) == 1
    assert "TARGET_DATABASE_URL is not set" in capsys.readouterr().out


def test_cli_refuses_a_target_that_is_not_postgresql(source_file, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TARGET_DATABASE_URL", f"sqlite:///{tmp_path / 'x.db'}")
    assert migration.main(["--source", str(source_file), "--execute"]) == 1
    assert "must be a PostgreSQL address" in capsys.readouterr().out
    assert not list(tmp_path.glob("*backup*"))  # nothing was done, not even a backup


def test_cli_never_prints_the_password_when_the_connection_fails(
    source_file, monkeypatch, capsys
):
    secret = "Zq7-Secret-Pass-Marker"
    monkeypatch.setenv(
        "TARGET_DATABASE_URL", f"postgresql://someone:{secret}@127.0.0.1:1/db?sslmode=require"
    )
    assert migration.main(["--source", str(source_file)]) == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "Nothing was changed" in output.out


def test_cli_rehearsal_then_execute_against_postgresql(source_file, tmp_path, monkeypatch, capsys):
    if not TEST_DATABASE_URL:
        pytest.skip("set TEST_DATABASE_URL to run against PostgreSQL")
    engine = _postgres_engine()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setenv("TARGET_DATABASE_URL", TEST_DATABASE_URL)
    before = sha256(source_file)
    try:
        # Rehearsal: succeeds, writes nothing, makes no backup.
        assert migration.main(["--source", str(source_file)]) == 0
        assert "REHEARSAL OK" in capsys.readouterr().out
        assert set(counts(engine).values()) == {0}
        assert not list(tmp_path.glob("*backup*"))

        # Real run: copies, makes a backup, leaves the source untouched.
        assert migration.main(["--source", str(source_file), "--execute"]) == 0
        assert "DONE" in capsys.readouterr().out
        assert counts(engine)["users"] == 3
        assert len(list(tmp_path.glob("meditrack-backup-*.db"))) == 1
        assert sha256(source_file) == before

        # Running it again must refuse, because the target now holds data.
        first_backup = next(tmp_path.glob("meditrack-backup-*.db"))
        first_backup_bytes = first_backup.read_bytes()
        assert migration.main(["--source", str(source_file), "--execute"]) == 1
        assert "not empty" in capsys.readouterr().out
        assert counts(engine)["users"] == 3
        # A refused run makes no new backup, and the earlier one is untouched.
        assert len(list(tmp_path.glob("meditrack-backup-*.db"))) == 1
        assert first_backup.read_bytes() == first_backup_bytes
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
