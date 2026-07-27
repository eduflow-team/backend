# Stage 2 백엔드 구현 메모 (Langflow 연동 handoff)

## 구현된 API (`/api/v1`)

| Method | Path | 비고 |
|--------|------|------|
| POST | `/teacher/assignments/step2` | multipart + mock Langflow + DB 저장 |
| GET | `/student/assignments/{id}/step2` | 상세·문서·시도·cleared_highlights |
| POST | `/student/assignments/{id}/step2/highlight` | 하이브리드 채점 + `stage2_highlight_submissions` 저장 |
| POST | `/student/assignments/{id}/step2/correction` | G-Eval 수정문 채점 + 최종 제출 1회 |

Form 필드: `title`, `subject`, `question`, `persona`, `hallucination_types`(JSON 배열 문자열), `expected_error_count`, `file`

## Highlight 채점 (`HighlightGrader` + `GEvalService`)

- **Rule-based**: `location_match_score` ≥ 0.8, `error_type` exact match
- **G-Eval**: `student_reason` → `reasoning_score` (θ_R ≥ 0.95)
- **판정**: 3조건 AND → `is_correct`
- `OPENAI_API_KEY` 없으면 G-Eval fallback(키워드 겹침) — smoke test용

## Correction 채점 (`GEvalService`)

- 선행: `highlight_phase_complete=true`, `corrections.length` = `expected_error_count`
- **G-Eval**: `factual_accuracy` + `completeness` 각 ≥ 4/5 (`STAGE2_CORRECTION_MIN_SCORE`)
- 저장: `submissions`(is_final), `stage2_correction_submissions`, `evaluations`, `student_assignment_status` COMPLETED
- **1회성** 재제출 → 403

환경변수: `STAGE2_LOCATION_THRESHOLD`, `STAGE2_REASONING_THRESHOLD`, `STAGE2_CORRECTION_MIN_SCORE`

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

## Stage2 API 4개 구현 완료
