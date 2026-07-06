"""도메인 전반에서 공통으로 사용하는 상태값 정의.

DB 컬럼 자체는 자유 문자열(`String`)이라 값 검증을 강제할 수 없으므로,
애플리케이션 코드에서는 매직 스트링을 직접 쓰지 않고 이 모듈에 정의된
값만 참조한다. 값을 추가/변경할 때도 이 파일만 수정하면 된다.
"""

from enum import Enum


class AttendanceStatus(str, Enum):
    """`attendance_records.status`에 저장되는 값."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    PENDING = "PENDING"


class ProgressStatus(str, Enum):
    """`student_assignment_status.progress_status`에 저장되는 값."""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
