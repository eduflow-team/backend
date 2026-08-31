<div align="center">

# EduFlow Backend

중·고등학생 **AI 리터러시** 교육 플랫폼 **에듀플로우**의 API 서버입니다.  
교사·학생 인증, 과제 출제·제출·채점, 학급 대시보드 데이터를 담당합니다.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=222222)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white&labelColor=222222)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white&labelColor=222222)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-vector-222222?style=flat-square&labelColor=222222)](https://github.com/pgvector/pgvector)

</div>

## 빠른 시작

```bash
# 1. 저장소 클론
git clone https://github.com/eduflow-team/backend.git
cd backend

# 2. 환경 변수 파일 생성
cp .env.example .env

# 3. 서버 실행
docker compose up -d --build

# 4. 마이그레이션
docker compose exec backend alembic upgrade head

# 5. API 문서 접속
open http://localhost:8000/docs
```
