from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String(80), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    listings: Mapped[List["PropertyListing"]] = relationship(back_populates="run")


class PropertyListing(Base):
    __tablename__ = "property_listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), index=True)
    site: Mapped[str] = mapped_column(String(80), index=True)
    external_id: Mapped[str] = mapped_column(String(120), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="EUR")
    status: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    beds: Mapped[Optional[float]] = mapped_column(nullable=True)
    baths: Mapped[Optional[float]] = mapped_column(nullable=True)
    built_area_m2: Mapped[Optional[float]] = mapped_column(nullable=True)
    plot_area_m2: Mapped[Optional[float]] = mapped_column(nullable=True)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    run: Mapped[ScrapeRun] = relationship(back_populates="listings")


def create_db_engine(database_url: str) -> Engine:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("sqlite:///"):
        db_path = Path(database_url.removeprefix("sqlite:///"))
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(database_url)


def create_session_factory(engine: Engine) -> sessionmaker:
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
