import app.models  # noqa: F401  (loads every table, including the chat tables)
import app.models.admin_audit  # noqa: F401  (the administrator audit log table)
from app.database import Base, engine


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("Tables are ready.")


if __name__ == "__main__":
    main()