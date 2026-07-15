# Stage 2 백엔드 구현 메모 (Langflow 연동 handoff)

## 구현된 API (`/api/v1`)

| Method | Path | 비고 |
|--------|------|------|
| POST | `/teacher/assignments/step2` | multipart + mock Langflow + DB 저장 |
| GET | `/student/assignments/{id}/step2` | 상세·문서·시도·cleared_highlights |

Form 필드: `title`, `subject`, `question`, `persona`, `hallucination_types`(JSON 배열 문자열), `expected_error_count`, `file`

## Langflow stub (AI 총괄)

`LangflowClient.run_stage2_hallucination` — `LANGFLOW_STAGE2_FLOW_ID`가 비어 있으면 mock.

교체 시:
- env: `LANGFLOW_URL`, `LANGFLOW_API_KEY`, `LANGFLOW_STAGE2_FLOW_ID`
- tweaks: `Prompt-s2gen`, `Prompt-s2ext` (`ai/docs/stage2-langflow-contract.md`)

## 저장 트랜잭션

1. `assignments` (stage=2, class_id=교사 `users.class_id`, max_attempts=5)
2. `documents` (raw_text, 벡터화 생략)
3. `stage2_assignment_details`
4. `stage2_error_answers`

## 미구현 (후속)

- `POST .../step2/highlight`
- `POST .../step2/correction`
