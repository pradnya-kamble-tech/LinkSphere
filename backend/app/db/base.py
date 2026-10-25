
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so SQLAlchemy registers their tables.
from app.models.user import User
from app.models.link import Link
from app.models.click_event import ClickEvent
