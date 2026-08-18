# Stage 3 백엔드 연동 메모

## Langflow 클라이언트

- 구현: `app/clients/stage3_langflow_client.py` (`Stage3LangflowClient`)
- 서비스: `app/services/stage3_service.py`에서 직접 사용
- 레거시: `LangflowClient.run_stage3_debate()`는 위 클라이언트로 위임

## 환경변수

| 변수 | 설명 |
|------|------|
| `LANGFLOW_STAGE3_V2_FLOW_ID` | v2 플로우 ID (우선) |
| `LANGFLOW_STAGE3_FLOW_ID` | v1 또는 v2 fallback ID |
| `LANGFLOW_STAGE3_V2_ENDPOINT` | ID 없을 때 lookup (`stage3-debate-v2`) |
| `STAGE3_ALLOW_MOCK` | `false`(기본): Langflow 없으면 **503**. `true`: 로컬 mock |

## v2 페르소나

v2는 LM `system_message` tweak를 쓰지 않는다(상대 발언 인용 끊김 방지).
대신 `input_value`에 논제·찬/반/팩트 페르소나를 함께 보낸다.

## Alembic

- revision: `20260815_stage3`
- parent: `c8d9e2f03b41` (stage2 set publish)
- `stage3_assignment_details.assignment_id` unique

## API 흐름

1. `POST /teacher/assignments/step3` — JSON 출제
2. `POST .../step3/debate` — Langflow 토론 (시도 1회 소비)
3. `POST .../step3/factcheck` — 발언별 판정 공개
4. `POST .../step3/submit` — `decisions` 생략·`[]` 모두 팩트체크 기록 사용

## Contract

- Flow: `ai/langflow/flows/stage3_debate_v2.json`
- Contract: `ai/docs/stage3-langflow-contract.md`
