from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Mod(Base):
    __tablename__ = "mods"
    __table_args__ = (UniqueConstraint("game_domain", "mod_id", name="uq_game_mod"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    game_domain: Mapped[str] = mapped_column(String(100))
    mod_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[str] = mapped_column(String(100), default="")
    author: Mapped[str] = mapped_column(String(255), default="")
    summary: Mapped[str] = mapped_column(String(500), default="")
    picture_url: Mapped[str] = mapped_column(String(500), default="")
    nexus_updated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Guild(Base):
    __tablename__ = "guilds"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("guild_id", "mod_pk", name="uq_guild_mod"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("guilds.guild_id", ondelete="CASCADE")
    )
    mod_pk: Mapped[int] = mapped_column(Integer, ForeignKey("mods.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
