from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class AttendanceRecord:
    email: str
    work_date: date
    start_time: str | None
    end_time: str | None


@dataclass
class OvertimeRecord:
    email: str
    work_date: date
    start_time: str | None
    end_time: str | None
    status: str | None
    apply_type: str | None
