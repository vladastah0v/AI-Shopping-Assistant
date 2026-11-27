from sqlalchemy import BigInteger, CheckConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CatalogRevision(Base):
    __tablename__ = "catalog_revision"
    __table_args__ = (CheckConstraint("singleton", name="singleton_true"),)

    singleton: Mapped[bool] = mapped_column(primary_key=True, server_default=text("true"))
    version: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
