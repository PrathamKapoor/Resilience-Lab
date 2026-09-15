"""SQLAlchemy models for the control plane."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class ExperimentRecord(Base):
    __tablename__ = "experiments"

    experiment_id = Column(String(256), primary_key=True)
    name = Column(String(512), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    description = Column(Text, nullable=False, default="")
    config_yaml = Column(Text, nullable=False)
    config_hash = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="CREATED", index=True)
    artifact_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    runs = relationship("RunRecord", back_populates="experiment", cascade="all, delete-orphan")
    events = relationship(
        "ExperimentEventRecord", back_populates="experiment", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_experiments_status_created", "status", "created_at"),)


class RunRecord(Base):
    __tablename__ = "runs"

    run_id = Column(String(512), primary_key=True)
    experiment_id = Column(
        String(256),
        ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_index = Column(Integer, nullable=False)
    seed = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="QUEUED", index=True)
    artifact_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    experiment = relationship("ExperimentRecord", back_populates="runs")

    __table_args__ = (Index("ix_runs_experiment_status", "experiment_id", "status"),)


class ExperimentEventRecord(Base):
    __tablename__ = "experiment_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(
        String(256),
        ForeignKey("experiments.experiment_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(String(512), nullable=True)
    event_type = Column(String(128), nullable=False)
    timestamp = Column(Float, nullable=False)
    elapsed = Column(Float, nullable=True)
    target_service = Column(String(256), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    experiment = relationship("ExperimentRecord", back_populates="events")

    __table_args__ = (Index("ix_events_experiment_type", "experiment_id", "event_type"),)
