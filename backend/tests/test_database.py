
from app.db.session import check_database_connection


def test_database_connection_is_available():
    assert check_database_connection() is True
