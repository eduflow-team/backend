"""로컬 개발용 DB seed (class + E2E 테스트 계정).

Notion E2E 계정과 동일:
  - 교사: e2e.teacher@example.com / Passw0rd!
  - 학생: e2e.student@example.com / Passw0rd!

사용:
  alembic upgrade head
  python scripts/seed_dev.py

멱등: 이미 있으면 건너뛰고 class·teacher 연결만 맞춘다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.class_ import Class
from app.models.user import User

E2E_PASSWORD = "Passw0rd!"
TEACHER_EMAIL = "e2e.teacher@example.com"
STUDENT_EMAIL = "e2e.student@example.com"
SEED_GRADE = 3
SEED_CLASS_NUMBER = 2


async def _get_class(session, grade: int, class_number: int) -> Class | None:
    stmt = select(Class).where(
        Class.grade == grade,
        Class.class_number == class_number,
        Class.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_user_by_email(session, email: str) -> User | None:
    stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        school_class = await _get_class(session, SEED_GRADE, SEED_CLASS_NUMBER)
        if school_class is None:
            school_class = Class(grade=SEED_GRADE, class_number=SEED_CLASS_NUMBER)
            session.add(school_class)
            await session.flush()
            print(f"created class_id={school_class.class_id} ({SEED_GRADE}학년 {SEED_CLASS_NUMBER}반)")
        else:
            print(f"reuse class_id={school_class.class_id} ({SEED_GRADE}학년 {SEED_CLASS_NUMBER}반)")

        teacher = await _get_user_by_email(session, TEACHER_EMAIL)
        if teacher is None:
            teacher = User(
                email=TEACHER_EMAIL,
                password_hash=hash_password(E2E_PASSWORD),
                name="E2E Teacher",
                phone="01000000001",
                role="TEACHER",
                class_id=school_class.class_id,
            )
            session.add(teacher)
            await session.flush()
            print(f"created teacher user_id={teacher.user_id} ({TEACHER_EMAIL})")
        else:
            if teacher.class_id != school_class.class_id:
                teacher.class_id = school_class.class_id
            print(f"reuse teacher user_id={teacher.user_id} ({TEACHER_EMAIL})")

        student = await _get_user_by_email(session, STUDENT_EMAIL)
        if student is None:
            student = User(
                email=STUDENT_EMAIL,
                password_hash=hash_password(E2E_PASSWORD),
                name="E2E Student",
                phone="01000000002",
                role="STUDENT",
                class_id=school_class.class_id,
            )
            session.add(student)
            await session.flush()
            print(f"created student user_id={student.user_id} ({STUDENT_EMAIL})")
        else:
            if student.class_id != school_class.class_id:
                student.class_id = school_class.class_id
            print(f"reuse student user_id={student.user_id} ({STUDENT_EMAIL})")

        if school_class.teacher_id != teacher.user_id:
            school_class.teacher_id = teacher.user_id
            print(f"linked class_id={school_class.class_id} -> teacher_id={teacher.user_id}")

        await session.commit()
        print("OK seed_dev complete")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
