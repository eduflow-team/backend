# Stage 1 백엔드 구현 메모 (Langflow 연동 handoff)

## 구현된 API (`/api/v1`)

| Method | Path | 비고 |
|--------|------|------|
| POST | `/teacher/assignments/step1` | multipart + 청킹·임베딩·`document_chunks` 저장 |
| GET | `/student/assignments/{id}/step1` | 상세·시도·최고점 |
| POST | `/student/assignments/{id}/step1/chat` | 검색·context·visualization 조립, **ai_response는 mock** |
| POST | `/student/assignments/{id}/step1/submit` | 시도 제한 3회 + 임시 채점(G-Eval 대체) |

Form 필드 (create): `class_id`, `subject`, `question`, `guideline`, `default_chunk_size`, `default_top_k`, `default_temperature`, `file`

## 채점 (하이브리드 C)

`submit`의 `_evaluate_response`:
1. **원문 비교**로 `faithfulness_score` / `relevance_score` / `current_score` 산출
2. **OpenAI chat**으로 학습용 `feedback` 생성 (`OPENAI_API_KEY` 없으면 템플릿 fallback)

응답 JSON 필드는 Notion 명세와 동일. 이후 Langflow G-Eval로 점수까지 교체 가능.

## Langflow stub (AI 총괄)

`AssignmentService.chat_step1` 안에서 `_mock_langflow_response`를 호출합니다.

교체 시 연결할 값:
- `message` ← request.message
- `context` ← 검색된 청크 합친 문자열 (이미 조립됨)
- `temperature` ← parameters.temperature
- env: `LANGFLOW_URL`, `LANGFLOW_API_KEY`, `LANGFLOW_STAGE1_CHAT_FLOW_ID`

tweaks 참고는 ai 레포 `prompts/stage1/handoff.md` / Flow ID.

## 환경변수

`.env.example`의 `OPENAI_API_KEY`, `LANGFLOW_*` 참고.
