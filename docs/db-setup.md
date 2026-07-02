# EduFlow DB 설정 가이드

PostgreSQL 16 + pgvector 기반 DB 레이어 구축 문서입니다.  
**ERD 원본**은 Notion DB 정리의 `ERD-1-revised.sql` 및 ERDCloud 수정본을 기준으로 합니다.

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| DB | PostgreSQL 16 |
| 벡터 검색 | **pgvector** (`document_chunks.embedding`) |
| ORM | SQLAlchemy 2.0 (async) + asyncpg |
| 마이그레이션 | Alembic |
| 애플리케이션 테이블 | **17개** (+ Alembic 메타 `alembic_version` 1개) |

ChromaDB/Milvus 대신 **pgvector**를 사용합니다. 임베딩·유사도 검색은 `document_chunks` 테이블에서 처리합니다.

---

## 2. 로컬 실행

### 최초 1회

```bash
cp .env.example .env
docker compose up -d db
docker compose run --rm backend alembic upgrade head
docker compose up -d backend
```

### pull 후 (스키마 변경이 있을 때)

```bash
docker compose up -d db
docker compose run --rm backend alembic upgrade head
```

### DB 접속 확인

- **Swagger**: http://localhost:8000/docs → **Health** → `GET /health/db`
- **curl**: `curl http://localhost:8000/health/db`  
  → `{"status":"success","data":{"db":"ok"}}`

### DataGrip

| 항목 | 값 |
|------|-----|
| Host | `localhost` |
| Port | `5432` |
| Database | `eduflow` |
| User / Password | `eduflow` / `eduflow` |

연결 후 `public` 스키마 **Refresh** → 테이블 17개 + `alembic_version` 확인.

---

## 3. 환경변수

`.env.example` 참고. 로컬 개발 기본값:

```
DATABASE_URL=postgresql+asyncpg://eduflow:eduflow@localhost:5432/eduflow
```

Docker **backend** 컨테이너 내부에서는 `docker-compose.yml`이 `@db:5432`로 override 합니다.

---

## 4. Alembic

| 명령 | 설명 |
|------|------|
| `alembic current` | 현재 DB revision 확인 |
| `alembic upgrade head` | 최신 마이그레이션 적용 |
| `alembic history` | 마이그레이션 이력 |

- 스키마 변경은 **모델 수정 + migration 파일**로만 반영 (DataGrip에서 테이블 직접 수정 금지)
- `alembic_version` 테이블은 Alembic이 자동 관리 (앱 테이블 아님)
- 초기 마이그레이션: `6031768b8c60_init_schema` — `CREATE EXTENSION vector` 포함

---

## 5. 스키마 요약

### 테이블 (17개)

| 영역 | 테이블 |
|------|--------|
| 계정·학급 | `users`, `refresh_tokens`, `classes` |
| 과제·문서 | `assignments`, `documents`, `document_chunks` |
| Stage 1/2 | `stage1_assignment_details`, `stage1_attempts`, `stage2_assignment_details`, `stage2_error_answers`, `stage2_highlight_submissions`, `stage2_correction_submissions` |
| 제출·평가 | `submissions`, `evaluations`, `student_assignment_status` |
| LMS | `attendance_records`, `notices` |

### 주요 포인트

- `document_chunks.embedding`: **`vector(768)`** (임베딩 모델 확정 후 차원 조정 가능)
- `submissions.is_final = true` → `evaluations` 채점 대상
- `stage1_attempts`, `stage2_*`: 중간 로그 (`submission_id` nullable)
- `student_assignment_status`: `(user_id, assignment_id)` UNIQUE
- `classes` ↔ `users`: 순환 FK (`teacher_id` / `class_id`)

### ERD 변경 요약 (이전 대비)

**추가·변경**
- `assignments.class_id` (학급 배포)
- stage1 환각/페르소나 설정 컬럼
- submissions ↔ stage* 테이블 FK 구조
- Dashboard 6영역 리터러시 점수 (`evaluations`)
- `document_chunks` + pgvector

**정리**
- 불필요 항목 제거·구조 통합 (상세는 Notion SQL / ERDCloud 참고)

---

## 6. Repository 레이어

```
API → Service → Repository → Model → PostgreSQL
```

`app/repositories/`에 ERD 17테이블 대응 Repository가 있습니다.

| Repository | 용도 |
|------------|------|
| `UserRepository`, `RefreshTokenRepository` | Auth (동원) |
| `DocumentRepository`, `DocumentChunkRepository` | 문서·RAG·벡터 검색 |
| `AssignmentRepository`, `SubmissionRepository` | 과제·제출 |
| `EvaluationRepository`, `StudentAssignmentStatusRepository` | 채점·대시보드 |
| Stage / Notice / Attendance 등 | 나머지 도메인 |

Service/API에서 사용 예:

```python
from fastapi import Depends
from app.repositories import AssignmentRepository, get_assignment_repository

async def example(repo: AssignmentRepository = Depends(get_assignment_repository)):
    return await repo.list_by_class(class_id=1)
```

`DocumentChunkRepository.search_similar()` — pgvector cosine distance 유사도 검색.

---

## 7. 동작 검증 (테스트 데이터)

FK 순서: `classes` → `users`(교사) → `classes.teacher_id` UPDATE → `users`(학생) → `assignments` → `documents` → `document_chunks`

DataGrip/psql 예시:

```sql
-- 체인 조회
SELECT c.class_id, u.name, a.title, d.filename, dc.chunk_id,
       vector_dims(dc.embedding) AS dims
FROM classes c
JOIN users u ON u.class_id = c.class_id
JOIN assignments a ON a.class_id = c.class_id
JOIN documents d ON d.assignment_id = a.assignment_id
JOIN document_chunks dc ON dc.document_id = d.document_id;
```

`vector_dims(embedding) = 768` 이면 정상.

---

## 8. 팀원 참고

### @류동원 (Auth / API)

- API path는 기존 stub 유지 — DB 연동은 Service에서 Repository 주입
- `users`, `refresh_tokens` migration 포함 → `UserRepository`, `RefreshTokenRepository` 사용 가능
- pgvector는 API로 노출하지 않음 (`document_chunks` 내부)

### @임정원 (AI / 임베딩)

- 임베딩 차원 **768 placeholder** — 모델 확정 후 migration 조정
- pgvector extension은 `alembic upgrade head` 시 자동 설치

### 공통

- **ERD 변경됨** — 작업 전 Notion `ERD-1-revised.sql` + ERDCloud 확인 필수
- 스키마 변경은 Alembic migration으로만

---

## 9. 후속 작업 (미구현)

- Stage 3/4 테이블
- `attendance_records` UNIQUE `(user_id, week_number)`
- `document_chunks.embedding` HNSW 인덱스
- Service 레이어 + API 실제 DB 연동

---

## 10. 프로젝트 구조 (DB 관련)

```
app/
├── db/              # engine, session, get_db
├── models/          # SQLAlchemy 모델 (17테이블)
├── repositories/    # DB 접근 레이어
alembic/
└── versions/        # 마이그레이션 파일
docs/
└── db-setup.md      # 이 문서
```
