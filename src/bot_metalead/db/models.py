from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as PgEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# =========================
# Base
# =========================
class Base(DeclarativeBase):
    pass


# =========================
# Enums
# =========================
class UserRole(str, enum.Enum):
    manager = "manager"
    employee = "employee"
    admin = "admin"


class TaskPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class TaskStatus(str, enum.Enum):
    new = "new"
    in_progress = "in_progress"
    on_review = "on_review"
    done = "done"
    rejected = "rejected"
    cancelled = "cancelled"


class ApprovalDecision(str, enum.Enum):
    approved = "approved"
    rejected = "rejected"


class ReminderType(str, enum.Enum):
    manual = "manual"
    auto = "auto"


class NoteStatus(str, enum.Enum):
    active = "active"
    done = "done"


class ScheduleType(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


# =========================
# Users
# =========================
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)

    username: Mapped[Optional[str]] = mapped_column(String(64))
    full_name: Mapped[Optional[str]] = mapped_column(String(255))

    role: Mapped[UserRole] = mapped_column(
        PgEnum(UserRole, name="user_role", create_constraint=True),
        nullable=False,
        default=UserRole.employee,
        server_default=UserRole.employee.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # relationships
    created_tasks: Mapped[List["Task"]] = relationship(
        "Task",
        foreign_keys=lambda: [Task.creator_id],
        back_populates="creator",
    )

    assigned_tasks: Mapped[List["Task"]] = relationship(
        "Task",
        foreign_keys=lambda: [Task.assignee_id],
        back_populates="assignee",
    )

    task_comments: Mapped[List["TaskComment"]] = relationship(
        "TaskComment",
        back_populates="author",
        cascade="all, delete-orphan",
    )

    task_approvals: Mapped[List["TaskApproval"]] = relationship(
        "TaskApproval",
        back_populates="manager",
        cascade="all, delete-orphan",
    )

    notes: Mapped[List["Note"]] = relationship(
        "Note",
        back_populates="owner",
        cascade="all, delete-orphan",
    )

    note_comments: Mapped[List["NoteComment"]] = relationship(
        "NoteComment",
        back_populates="author",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_role", "role"),
    )


# =========================
# Tasks
# =========================
class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    creator_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assignee_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    priority: Mapped[TaskPriority] = mapped_column(
        PgEnum(TaskPriority, name="task_priority", create_constraint=True),
        nullable=False,
        default=TaskPriority.medium,
        server_default=TaskPriority.medium.value,
    )

    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    status: Mapped[TaskStatus] = mapped_column(
        PgEnum(TaskStatus, name="task_status", create_constraint=True),
        nullable=False,
        default=TaskStatus.new,
        server_default=TaskStatus.new.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    taken_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # relationships (ВАЖНО: только один раз)
    creator: Mapped["User"] = relationship(
        "User",
        foreign_keys=lambda: [Task.creator_id],
        back_populates="created_tasks",
    )
    assignee: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=lambda: [Task.assignee_id],
        back_populates="assigned_tasks",
    )

    comments: Mapped[List["TaskComment"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    approvals: Mapped[List["TaskApproval"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reminders: Mapped[List["TaskReminder"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_tasks_creator_id", "creator_id"),
        Index("idx_tasks_assignee_id", "assignee_id"),
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_deadline_at", "deadline_at"),
        Index("idx_tasks_priority", "priority"),
    )

# =========================
# Task comments
# =========================
class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    task: Mapped["Task"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship(back_populates="task_comments")

    __table_args__ = (
        Index("idx_task_comments_task_id", "task_id"),
        Index("idx_task_comments_author_id", "author_id"),
        Index("idx_task_comments_created_at", "created_at"),
    )


# =========================
# Task approvals (manager decision)
# =========================
class TaskApproval(Base):
    __tablename__ = "task_approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    manager_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    decision: Mapped[ApprovalDecision] = mapped_column(
        PgEnum(ApprovalDecision, name="approval_decision", create_constraint=True),
        nullable=False,
    )
    comment: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    task: Mapped["Task"] = relationship(back_populates="approvals")
    manager: Mapped["User"] = relationship(back_populates="task_approvals")

    __table_args__ = (
        # один менеджер — одно решение на задачу (если нужно несколько — убирай)
        UniqueConstraint("task_id", "manager_id", name="uq_task_approvals_task_manager"),
        Index("idx_task_approvals_task_id", "task_id"),
        Index("idx_task_approvals_manager_id", "manager_id"),
        Index("idx_task_approvals_created_at", "created_at"),
    )


# =========================
# Task reminders
# =========================
class TaskReminder(Base):
    __tablename__ = "task_reminders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    type: Mapped[ReminderType] = mapped_column(
        PgEnum(ReminderType, name="reminder_type", create_constraint=True),
        nullable=False,
        default=ReminderType.auto,
        server_default=ReminderType.auto.value,
    )

    is_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    task: Mapped["Task"] = relationship(back_populates="reminders")

    __table_args__ = (
        Index("idx_task_reminders_task_id", "task_id"),
        Index("idx_task_reminders_remind_at", "remind_at"),
        Index("idx_task_reminders_is_sent", "is_sent"),
    )


# =========================
# Notes
# =========================
class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    status: Mapped[NoteStatus] = mapped_column(
        PgEnum(NoteStatus, name="note_status", create_constraint=True),
        nullable=False,
        default=NoteStatus.active,
        server_default=NoteStatus.active.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    owner: Mapped["User"] = relationship(back_populates="notes")

    comments: Mapped[List["NoteComment"]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    reminders: Mapped[List["NoteReminder"]] = relationship(
        back_populates="note",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_notes_owner_id", "owner_id"),
        Index("idx_notes_status", "status"),
        Index("idx_notes_updated_at", "updated_at"),
    )


# =========================
# Note comments
# =========================
class NoteComment(Base):
    __tablename__ = "note_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    note_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notes.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    note: Mapped["Note"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship(back_populates="note_comments")

    __table_args__ = (
        Index("idx_note_comments_note_id", "note_id"),
        Index("idx_note_comments_author_id", "author_id"),
        Index("idx_note_comments_created_at", "created_at"),
    )


# =========================
# Note reminders (scheduled)
# =========================
class NoteReminder(Base):
    __tablename__ = "note_reminders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    note_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notes.id", ondelete="CASCADE"),
        nullable=False,
    )

    schedule_type: Mapped[ScheduleType] = mapped_column(
        PgEnum(ScheduleType, name="schedule_type", create_constraint=True),
        nullable=False,
    )

    hour: Mapped[int] = mapped_column(Integer, nullable=False)
    minute: Mapped[int] = mapped_column(Integer, nullable=False)

    # weekly
    weekday: Mapped[Optional[int]] = mapped_column(Integer)  # 0-6

    # monthly
    day_of_month: Mapped[Optional[int]] = mapped_column(Integer)  # 1-31

    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    last_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    note: Mapped["Note"] = relationship(back_populates="reminders")

    __table_args__ = (
        # базовые проверки валидности
        CheckConstraint("hour BETWEEN 0 AND 23", name="ck_note_reminders_hour"),
        CheckConstraint("minute BETWEEN 0 AND 59", name="ck_note_reminders_minute"),
        CheckConstraint("(weekday IS NULL) OR (weekday BETWEEN 0 AND 6)", name="ck_note_reminders_weekday"),
        CheckConstraint("(day_of_month IS NULL) OR (day_of_month BETWEEN 1 AND 31)", name="ck_note_reminders_dom"),
        Index("idx_note_reminders_note_id", "note_id"),
        Index("idx_note_reminders_enabled", "is_enabled"),
        Index("idx_note_reminders_schedule", "schedule_type", "hour", "minute"),
    )