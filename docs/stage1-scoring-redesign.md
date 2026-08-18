# Stage1 채점·학습 모델 재설계 (결정 메모)

> 상태: **결정만 저장** — 아직 구현하지 않음  
> 날짜: 2026-08-16

## 학습 목표 (방향)

- 이전: AI 답변 품질을 점수화 / (숨은) optimal 파라미터 근접 채점
- 이후: **정답이 있는 과제 문제**를 학생이 풀고, AI와 대화·파라미터 조절로 근거를 찾아 **본인 답을 제출**
- 파라미터가 약해서 답이 틀린 것은 괜찮음
- 기본값보다 자원을 과하게 키워 “쉽게만” 맞히려는 경우 감점

## 채점 방식 (채택)

**최종 = 정답점수 − 사용량(리소스) 감점** (하한 0)

### 1) 정답점수 (주점수, 0~100)

- 맞춤 → 100 / 틀림 → 0 (부분점수는 추후 여지)
- 약한 파라미터로 틀린 것은 **정답점수에만** 반영 (별도 “약함 감점” 없음)
- 제출 본문 = 학생이 작성한 답안 (AI 말풍선 선택 제출 폐기 방향)

### 2) 사용량 감점

- 기준점: **교사 default 파라미터** (`default_chunk_size` / `default_top_k` / `default_temperature`)
  - ~~숨은 `optimal_parameters` 근접 채점~~ → 이번 방향에서는 **사용하지 않음** (폐기/축소)
- default보다 **크게** 올린 만큼만 감점
- default보다 **작게** 쓴 것은 감점 0
- 1차 감점 축: `top_k`, `chunk_size` (비중: top_k 0.6 / chunk 0.4)
- `temperature`: **감점 제외** (확정)
- `k_scale=6`, `chunk_scale=3`, `w=0.3` (최대 약 30점 감점) — 확정
- 정답 채점: 정규화 후 완전일치, 정답 1개, 제출 2회, 정답 공개는 마감 후, 채팅 자유 질문

### 3) 식 (초안)

제출 시점 파라미터 `(chunk, k, t)`, 교사 default `(chunk0, k0, t0)`:

```
penalty_k     = max(0, k - k0) / k_scale
penalty_chunk = max(0, chunk_index - chunk0_index) / chunk_scale
resource_penalty = 100 × clamp(0.6·penalty_k + 0.4·penalty_chunk, 0, 1)
final = max(0, correct_score - w × resource_penalty)
```

- `k_scale`, `chunk_scale`, `w`는 구현 시 튜닝
- 채팅 횟수 감점은 선택(남용 방지용), 필수 아님

## 함께 가져갈 기능 방향 (채점 외, 구현 시)

1. top-k: 학생이 **보고 수정**할 수 있게
2. **교사 출제 퀴즈 1문제** + 정답 + 학생 답안 제출
3. 이미지 PDF → 텍스트 변환 저장, 그림·잡음 제거, chunk / top-k 결과 확인 UI
4. AI 채팅은 **힌트·근거 탐색 수단** (제출 본문 아님)
5. 교사: 문제·정답 직접 입력 UX (AI 자동 출제 아님)

## 출제 (추가 확정)

- 문항 수: **1문제**
- 출제 주체: **교사** (PDF 기반 AI 자동 출제보다 채점 안정성 우선)
- AI 문제 초안 생성은 선택 기능으로 나중에 검토

## 확정 수치·정책 (2026-08-18)

→ 상세: [`stage1-redesign-checklist.md`](./stage1-redesign-checklist.md) §0

## 참고

- 할 일 체크리스트: [`stage1-redesign-checklist.md`](./stage1-redesign-checklist.md)
- 현재 구현(변경 전): `final = 0.8×optimal근접 + 0.2×답변품질`, 제출 = `selected_ai_response`
- 관련 기존 메모: `docs/stage1-backend-notes.md` (현행 동작 설명; 본 문서와 충돌 시 **본 문서·체크리스트가 새 방향**)
