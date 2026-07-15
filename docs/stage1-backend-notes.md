# Stage 1 백엔드 구현 메모 (Langflow 연동 handoff)

## 구현된 API (`/api/v1`)

| Method | Path | 비고 |
|--------|------|------|
| POST | `/teacher/assignments/step1` | multipart + preset 5종 병렬 임베딩 → `document_chunks` |
| GET | `/student/assignments/{id}/step1` | 상세·시도·최고점 |
| POST | `/student/assignments/{id}/step1/chat` | 검색·context·visualization 조립, **ai_response는 mock** |
| POST | `/student/assignments/{id}/step1/submit` | 시도 제한 3회 + 하이브리드 채점 + `student_prompt` 저장 |

Form 필드 (create): `class_id`, `subject`, `question`, `guideline`, `default_chunk_size`, `default_top_k`, `default_temperature`, `file`

submit Body: `final_parameters`, `selected_ai_response`, `student_prompt` (필수)

---

## 최근 반영 (리뷰 후속)

동원님 PR 코멘트 기준으로 반영한 내용입니다.

### 1) chat 검색·생성 분리 (재임베딩 방지)

- `top_k` / `temperature`만 바꿔도 문서 전체 재임베딩하지 않음
- 흐름: DB(또는 fallback)에서 청크 벡터 로드 → **질문만** 임베딩 → cosine → `top_k` → 생성
- `temperature`는 mock/Langflow 생성에만 사용

### 2) chunk_size preset 사전 임베딩

- 허용값: **`50 / 200 / 500 / 1200 / 3000`** (`settings.STAGE1_CHUNK_SIZE_PRESETS`)
- create·chat·submit에서 preset 밖 → **400**
- 업로드 시 preset 5개를 **병렬 임베딩** 후 `document_chunks.metadata.chunk_size`로 구분 저장
- chat은 해당 size DB 벡터 **재사용**
- 구 과제에 해당 size가 없을 때만 실시간 임베딩 fallback
- 프론트: chunk_size는 숫자 자유 입력이 아니라 **preset 선택**

### 3) `is_final` — 마지막 제출만 true

- submit마다 같은 학생·과제의 이전 `submissions.is_final`을 `false`로 해제
- **방금 제출한 1건만** `true`
- records 도메인 대표 제출 기준과 맞춤
- 1번만 내고 끝내도 그 1건이 final

### 4) `student_prompt` 저장

- submit Request에 `student_prompt` 필수 (chat 때 쓴 `message`)
- `stage1_attempts.student_prompt`에 저장 (시도별 학생 질문 기록)
- Notion: [최종 답변 제출 및 채점](https://www.notion.so/cfcaa449c9d9826fb6cf816e8fd621e7) Body에 반영됨
- GET step1은 이력 목록을 내려주지 않음 (저장만; 조회 API는 후속)

---

## 채점 (하이브리드 C)

`submit`의 `_evaluate_response`:
1. **원문 비교**로 `faithfulness_score` / `relevance_score` / `current_score` 산출
2. **OpenAI chat**으로 학습용 `feedback` 생성 (`OPENAI_API_KEY` 없으면 템플릿 fallback)

응답 JSON 필드는 Notion 명세와 동일. 이후 Langflow G-Eval로 점수까지 교체 가능.

---

## Langflow stub (AI 총괄)

`AssignmentService.chat_step1` 안에서 `_mock_langflow_response`를 호출합니다.

교체 시 연결할 값:
- `message` ← request.message
- `context` ← 검색된 청크 합친 문자열 (이미 조립됨)
- `temperature` ← parameters.temperature
- env: `LANGFLOW_URL`, `LANGFLOW_API_KEY`, `LANGFLOW_STAGE1_CHAT_FLOW_ID`

tweaks 참고는 ai 레포 `prompts/stage1/handoff.md` / Flow ID.

---

## 환경변수

`.env.example`의 `OPENAI_API_KEY`, `LANGFLOW_*` 참고.  
chunk_size preset은 코드 상수 (`STAGE1_CHUNK_SIZE_PRESETS`).
