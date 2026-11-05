import threading

from sqlalchemy import text

from app.database.session import engine, get_db


def test_database_connection():
    assert engine.dialect.name == "sqlite"
    with engine.connect() as connection:
        result = connection.execute(text("SELECT 1")).scalar_one()
    assert result == 1


def test_sqlite_connection_can_be_used_from_another_thread():
    with engine.connect() as connection:
        errors = []

        def run():
            try:
                connection.execute(text("SELECT 1")).scalar_one()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()

    assert errors == []


def test_get_db_closes_session():
    db_generator = get_db()
    db = next(db_generator)
    assert db.execute(text("SELECT 1")).scalar_one() == 1
    assert db.in_transaction() is True

    closed = {"called": False}
    original_close = db.close

    def tracking_close():
        closed["called"] = True
        original_close()

    db.close = tracking_close
    try:
        next(db_generator)
    except StopIteration:
        pass

    assert closed["called"] is True
    assert db.in_transaction() is False
