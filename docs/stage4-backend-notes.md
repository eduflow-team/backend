# Stage 4 백엔드 구현 메모 (힌트 · 채점)

상세 계약: `ai/docs/stage4-scoring.md` · `ai/docs/stage4-langflow-contract.md`

## 채점 모듈

`app/services/grading/stage4_grader.py` — `Stage4Grader`

| 메서드 | 역할 |
|--------|------|
| `classify_attack(prompt)` | weak / medium / strong / combo |
| `is_attack_success(..., difficulty, attack_prompt)` | 키 포함 + 난이도 최소 티어 |
| `hint_for(difficulty, failed_count, is_cleared)` | 실패 2/4/6 → hint level 1/2/3 |
| `evaluate_report(...)` | clear 40 + efficiency 30 + analysis 30 |

### 클리어 티어

| 난이도 | 최소 공격 티어 |
|--------|----------------|
| EASY | weak |
| NORMAL | medium |
| HARD | combo (역할+승인+형식+실제값) |

합격선: `current_score >= 60`

## 점수

| 항목 | 배점 |
|------|------|
| clear_score | 40 |
| efficiency_score | 최대 30 |
| analysis_score | 최대 30 (부분점수 + 개념 키워드) |

## 힌트

- 백엔드 결정 → Langflow tweaks `hint`
- 정답 문장 직접 제공 금지, 방향만
- chat 응답: `hint`, `hint_level`

## API

- [x] `POST /teacher/assignments/step4`
- [x] `GET /student/assignments/{id}/step4`
- [x] `POST .../step4/chat` + `LangflowClient.run_stage4_chat`
- [x] `POST .../step4/submit` → `Stage4Grader.evaluate_report`

## 캘리브레이션

`scripts/stage4_calibration_battery.py`  
결과: `ai/docs-local/calibration/` (로컬 전용)
