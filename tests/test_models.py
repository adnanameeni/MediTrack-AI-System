from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, event, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.models import BloodPressureReading, GlucoseReading, ReadingType, User


def _test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def test_models_create_tables():
    engine = _test_engine()
    Base.metadata.create_all(engine)
    table_names = set(inspect(engine).get_table_names())

    assert {"users", "glucose_readings", "blood_pressure_readings"} <= table_names
    assert "password" not in inspect(engine).get_columns("users")
    user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {
        "id",
        "full_name",
        "email",
        "hashed_password",
        "created_at",
        "is_active",
    } <= user_columns

    email_indexes = inspect(engine).get_indexes("users")
    assert any(index["unique"] and index["column_names"] == ["email"] for index in email_indexes)

    glucose_indexes = inspect(engine).get_indexes("glucose_readings")
    assert any(
        index["column_names"] == ["user_id", "recorded_at"] for index in glucose_indexes
    )
    pressure_indexes = inspect(engine).get_indexes("blood_pressure_readings")
    assert any(
        index["column_names"] == ["user_id", "recorded_at"] for index in pressure_indexes
    )


def test_user_reading_relationships():
    engine = _test_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    user = User(
        full_name="Example User",
        email="example.user@example.com",
        hashed_password="not-a-plaintext-password",
    )
    user.glucose_readings.append(
        GlucoseReading(
            glucose_value=Decimal("101.50"),
            reading_type=ReadingType.FASTING,
            notes=None,
        )
    )
    user.blood_pressure_readings.append(
        BloodPressureReading(systolic=120, diastolic=80, pulse=70, notes=None)
    )
    session.add(user)
    session.commit()

    stored_user = session.get(User, user.id)
    assert stored_user.created_at is not None
    assert stored_user.is_active is True
    assert len(stored_user.glucose_readings) == 1
    assert len(stored_user.blood_pressure_readings) == 1

    glucose = stored_user.glucose_readings[0]
    pressure = stored_user.blood_pressure_readings[0]
    assert glucose.user.id == stored_user.id
    assert pressure.user.id == stored_user.id
    assert glucose.reading_type == ReadingType.FASTING
    assert Decimal(glucose.glucose_value) == Decimal("101.50")
    assert pressure.pulse == 70
    assert glucose.recorded_at is not None
    assert pressure.recorded_at is not None
    session.close()


def test_user_email_is_unique():
    engine = _test_engine()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(
        User(
            full_name="Example User",
            email="duplicate@example.com",
            hashed_password="hash-one",
        )
    )
    session.commit()
    session.add(
        User(
            full_name="Another Example",
            email="duplicate@example.com",
            hashed_password="hash-two",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
    session.close()


# ---------------------------------------------------------------------------
# Extra tests added for Stage 3. Everything below uses a fresh in-memory
# SQLite database and made-up example data only.
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    engine = _test_engine()
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()
    engine.dispose()


def _make_user(db, email="example.user@example.com"):
    user = User(
        full_name="Example User",
        email=email,
        hashed_password="not-a-plaintext-password",
    )
    db.add(user)
    db.commit()
    return user


def _count(db, model):
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_users_table_has_no_plain_password_column(session):
    columns = {column["name"] for column in inspect(session.get_bind()).get_columns("users")}
    assert "password" not in columns
    assert "hashed_password" in columns


def test_foreign_keys_point_to_users(session):
    inspector = inspect(session.get_bind())
    for table in ("glucose_readings", "blood_pressure_readings"):
        foreign_keys = inspector.get_foreign_keys(table)
        assert any(
            fk["referred_table"] == "users" and fk["constrained_columns"] == ["user_id"]
            for fk in foreign_keys
        )


def test_glucose_reading_requires_existing_user(session):
    session.add(
        GlucoseReading(
            user_id=999,
            glucose_value=Decimal("100.00"),
            reading_type=ReadingType.FASTING,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_blood_pressure_reading_requires_existing_user(session):
    session.add(BloodPressureReading(user_id=999, systolic=120, diastolic=80))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("bad_value", [Decimal("0"), Decimal("-5.00")])
def test_glucose_value_must_be_positive(session, bad_value):
    user = _make_user(session)
    session.add(
        GlucoseReading(
            user_id=user.id,
            glucose_value=bad_value,
            reading_type=ReadingType.FASTING,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    "reading_type",
    [ReadingType.FASTING, ReadingType.BEFORE_MEAL, ReadingType.AFTER_MEAL],
)
def test_glucose_accepts_all_valid_reading_types(session, reading_type):
    user = _make_user(session)
    session.add(
        GlucoseReading(
            user_id=user.id,
            glucose_value=Decimal("95.00"),
            reading_type=reading_type,
        )
    )
    session.commit()
    assert _count(session, GlucoseReading) == 1


def test_database_rejects_invalid_glucose_reading_type(session):
    user = _make_user(session)
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO glucose_readings (user_id, glucose_value, reading_type) "
                "VALUES (:user_id, 100, 'not_a_real_type')"
            ),
            {"user_id": user.id},
        )


@pytest.mark.parametrize(
    ("systolic", "diastolic"),
    [(0, -1), (-120, -130), (120, 0), (120, -5)],
)
def test_blood_pressure_values_must_be_positive(session, systolic, diastolic):
    user = _make_user(session)
    session.add(
        BloodPressureReading(user_id=user.id, systolic=systolic, diastolic=diastolic)
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(("systolic", "diastolic"), [(80, 120), (100, 100)])
def test_systolic_must_be_greater_than_diastolic(session, systolic, diastolic):
    user = _make_user(session)
    session.add(
        BloodPressureReading(user_id=user.id, systolic=systolic, diastolic=diastolic)
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize("bad_pulse", [0, -1])
def test_pulse_must_be_positive_when_given(session, bad_pulse):
    user = _make_user(session)
    session.add(
        BloodPressureReading(
            user_id=user.id, systolic=120, diastolic=80, pulse=bad_pulse
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_pulse_and_notes_are_optional(session):
    user = _make_user(session)
    session.add(BloodPressureReading(user_id=user.id, systolic=120, diastolic=80))
    session.commit()

    reading = session.execute(select(BloodPressureReading)).scalar_one()
    assert reading.pulse is None
    assert reading.notes is None


def test_valid_readings_are_saved_with_timestamps(session):
    user = _make_user(session)
    session.add_all(
        [
            GlucoseReading(
                user_id=user.id,
                glucose_value=Decimal("110.25"),
                reading_type=ReadingType.AFTER_MEAL,
                notes="Example note",
            ),
            BloodPressureReading(
                user_id=user.id, systolic=118, diastolic=76, pulse=64
            ),
        ]
    )
    session.commit()

    glucose = session.execute(select(GlucoseReading)).scalar_one()
    pressure = session.execute(select(BloodPressureReading)).scalar_one()
    assert glucose.recorded_at is not None
    assert pressure.recorded_at is not None
    assert glucose.notes == "Example note"


def test_deleting_user_deletes_their_readings(session):
    user = _make_user(session)
    user.glucose_readings.append(
        GlucoseReading(glucose_value=Decimal("100.00"), reading_type=ReadingType.FASTING)
    )
    user.blood_pressure_readings.append(
        BloodPressureReading(systolic=120, diastolic=80)
    )
    session.commit()
    assert _count(session, GlucoseReading) == 1
    assert _count(session, BloodPressureReading) == 1

    session.delete(user)
    session.commit()

    assert _count(session, User) == 0
    assert _count(session, GlucoseReading) == 0
    assert _count(session, BloodPressureReading) == 0


def test_database_cascades_delete_without_the_orm(session):
    user = _make_user(session)
    user.glucose_readings.append(
        GlucoseReading(glucose_value=Decimal("100.00"), reading_type=ReadingType.FASTING)
    )
    session.commit()

    session.execute(delete(User).where(User.id == user.id))
    session.commit()

    assert _count(session, GlucoseReading) == 0


def test_users_only_see_their_own_readings(session):
    first = _make_user(session, "first.example@example.com")
    second = _make_user(session, "second.example@example.com")
    first.blood_pressure_readings.append(
        BloodPressureReading(systolic=120, diastolic=80)
    )
    session.commit()

    assert len(first.blood_pressure_readings) == 1
    assert second.blood_pressure_readings == []