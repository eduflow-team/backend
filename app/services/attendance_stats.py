"""출석 기록 집계·정규화 로직 (Attendance API / Dashboard 공통)."""

from app.models.attendance import AttendanceRecord
from app.models.enums import AttendanceStatus

_KNOWN_STATUSES = {s.value for s in AttendanceStatus}


def normalize_attendance_status(raw: str | None) -> str | None:
    if raw is None:
        return None
    upper = raw.upper()
    if upper in _KNOWN_STATUSES:
        return upper
    return None


def compute_attendance_summary(
    records: list[AttendanceRecord],
) -> tuple[float, int, int, int]:
    """출석률과 status별 건수를 반환한다.

    출석률 = (PRESENT + LATE) / (PRESENT + LATE + ABSENT) * 100
    PENDING 및 알 수 없는 status는 건수·출석률 계산에서 제외한다.
    """

    present_count = late_count = absent_count = 0
    for record in records:
        status = normalize_attendance_status(record.status)
        if status == AttendanceStatus.PRESENT.value:
            present_count += 1
        elif status == AttendanceStatus.LATE.value:
            late_count += 1
        elif status == AttendanceStatus.ABSENT.value:
            absent_count += 1

    finalized = present_count + late_count + absent_count
    attendance_rate = (
        round((present_count + late_count) / finalized * 100, 1) if finalized else 0.0
    )
    return attendance_rate, present_count, late_count, absent_count
