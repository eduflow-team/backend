# Stage 4 백엔드 구현 메모 (힌트 · 채점)

상세 계약: `ai/docs/stage4-scoring.md` · `ai/docs/stage4-langflow-contract.md`

## 채점 모듈

`app/services/grading/stage4_grader.py` — `Stage4Grader`

| 메서드 | 역할 |
|--------|------|
| `is_attack_success(secret_key, ai_response)` | Rule: `secret_key in ai_response` |
| `hint_for(difficulty, failed_count, is_cleared)` | 실패 2/4/6 → hint level 1/2/3 |
| `evaluate_report(...)` | clear 40 + efficiency 30 + analysis 30 |

합격선: `current_score >= 60`

## 점수

| 항목 | 배점 |
|------|------|
| clear_score | 40 (클리어 후 제출이므로 고정) |
| efficiency_score | 최대 30, `(max-used+1)/max * 30 * coef` |
| analysis_score | 최대 30, 보고서 4필드 루브릭 |

보고서 루브릭 필드 (Notion submit body):

- `successful_attacks` (6)
- `failed_attacks` (6)
- `why_breached` (9)
- `defense_ideas` (9, 아이디어 2개+)

## 힌트

- 백엔드가 결정 → Langflow tweaks `hint`
- 클리어 후 / 실패 0~1회: 힌트 없음
- chat 응답에 `hint`, `hint_level` 포함 예정

## TODO (API)

- [ ] `POST /teacher/assignments/step4`
- [ ] `GET /student/assignments/{id}/step4`
- [ ] `POST /student/assignments/{id}/step4/chat` + `LangflowClient.run_stage4_chat`
- [ ] `POST /student/assignments/{id}/step4/submit` → `Stage4Grader.evaluate_report`
- [ ] DB: stage4 detail / attack logs / report submission
