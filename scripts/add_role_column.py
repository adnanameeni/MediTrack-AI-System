"""Adds the 'role' column to an existing users table. Safe to run more than once.

Run once on your existing database:  python -m scripts.add_role_column
Existing users are NOT changed or deleted; every one of them becomes role 'user'.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database import engine as default_engine


def add_role_column(engine: Engine) -> bool:
    """Add users.role if it is missing. Returns True if it was added."""
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        raise RuntimeError(
            "The users table does not exist yet. Run: python -m scripts.create_tables"
        )
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "role" in columns:
        return False
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'")
        )
    return True


def main() -> None:
    if add_role_column(default_engine):
        print("Added the 'role' column. Every existing user is now a normal user.")
    else:
        print("The 'role' column already exists. Nothing to do.")


if __name__ == "__main__":
    main()