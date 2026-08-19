# Stage2 고도화 — DB 수정

## 배경

카드형 세트 출제: PDF 1회 → 후보 카드 N장 생성 → 교사 미리보기·선택 → 배포.  
과제 1장 = 환각 1개 (`expected_error_count=1`). 기존 `stage2_*` / 학생 제출 테이블 구조는 유지.

## 변경 범위 (소규모)

`assignments` 테이블만 수정. 신규 테이블 없음.

| 컬럼 | 타입 | Nullable | Default | 설명 |
|------|------|----------|---------|------|
| `set_id` | BIGINT | YES | NULL | 같은 세트에 속한 카드(과제) 묶음. 첫 카드 `assignment_id`를 `set_id`로 사용 |
| `publish_status` | VARCHAR(20) | NO | `'PUBLISHED'` | `DRAFT` / `PUBLISHED`. 학생·대시보드는 PUBLISHED만 노출 |

## 기존 데이터

- 마이그레이션 시 기존 `assignments` 행: `publish_status = 'PUBLISHED'`, `set_id = NULL`

## 변경하지 않음

- `stage2_assignment_details`, `stage2_error_answers`, `documents`, 학생 highlight/correction/submission 테이블

## 백엔드 연동

- 세트 생성 시 카드마다 동일 `set_id`, `publish_status = 'DRAFT'`
- `PATCH /teacher/assignments/step2/set/{set_id}` 배포 시 선택 카드만 `PUBLISHED`
- 학생 `get_step2` / 대시보드: `publish_status = 'PUBLISHED'` 필터

## MVP 대안 (migration 0)

배포 시점에만 `assignments` insert → `publish_status` 없이도 가능. 미리보기는 API 응답만.
