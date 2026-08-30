# Stage 1 백엔드 구현 메모 (퀴즈 재설계)

> 기존 Stage1 과제·제출은 마이그레이션 `b2c3d4e5f6a7`에서 **삭제**됨. 과제 재출제 필요.  
> 기획: `stage1-redesign-checklist.md`, `stage1-scoring-redesign.md`

## API

| Method | Path | 비고 |
|--------|------|------|
| POST | `/teacher/assignments/step1` | multipart: `question`, `answer_keypoints`(JSON 3개), `file`, `due_at` … |
| GET | `/student/assignments/{id}/step1` | 문제·자료텍스트·파라미터. 키포인트는 **마감 후**만 |
| POST | `/student/assignments/{id}/step1/chat` | 자유 `message` + 파라미터. chunk preview 포함 |
| POST | `/student/assignments/{id}/step1/submit` | `student_answer` + `final_parameters` |

### create Form
`class_id`, `subject`, `question`, `answer_keypoints`(JSON 문자열 배열 3개), `due_at`, `file`  
시작 파라미터는 서버 고정: **chunk 50 · top_k 2 · temperature 1.0** (`STAGE1_DEFAULT_*`)

### submit Body
```json
{ "final_parameters": { "chunk_size", "top_k", "temperature" }, "student_answer": "..." }
```
답안 최소 길이: `STAGE1_MIN_STUDENT_ANSWER_CHARS`(기본 20)

### chat visualization
`total_chunks`, `retrieved_chunks`, `vector_search_score`, `retrieved_chunk_previews`, `approx_context_chars`

## 채점

- 제출 **2회** (`STAGE1_MAX_ATTEMPTS=2`)
- `final = max(0, correct_score − resource_penalty)`
  - 키포인트 N개 중 반영된 비율 → `correct_score` (전부 맞으면 100, `is_correct`)
  - 리소스 감점: 교사 **default**보다 키운 `top_k`·`chunk_size`만 (`w=0.3`, 최대 ~30). temperature 제외
- 정답 키포인트: 마감 전에는 API에 미포함 (`answer` 컬럼에 JSON 저장)

## PDF / OCR

- pypdf → (부족 시) Tesseract → OpenAI Vision
- 추출 후 `_normalize_extracted_text`로 URL·짧은 노이즈 줄 정리 → `documents.raw_text`
- create 시 preset 5종 청킹·임베딩 유지 (chat 시 재사용)

## Langflow

env: `LANGFLOW_URL`, `LANGFLOW_API_KEY`, `LANGFLOW_STAGE1_*`  
채팅은 근거 탐색용 (제출 본문 아님).

### WEAK / STRONG context 래핑

검색 품질이 약하면 Langflow용 `context`에 `[내부모드: WEAK]` + 시대착오 노이즈를 붙인다.  
충분하면 `[내부모드: STRONG]`. 학생 UI `retrieved_chunk_previews`에는 **실청크만**.

판정(기본): `chunk_size<=50` and `top_k<=2` → WEAK, 아니면 STRONG  
코드: `app/services/stage1_context.py` · 설정: `STAGE1_WEAK_*`  
WEAK에서 모델이 상식으로 바른 힌트만 주면 `STAGE1_WEAK_FORCE_HALLUCINATION`으로 오답 키워드 답변을 코드 보정한다.
