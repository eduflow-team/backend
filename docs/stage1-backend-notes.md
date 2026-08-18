# Stage 1 백엔드 구현 메모 (퀴즈 재설계)

> 기존 Stage1 과제·제출은 마이그레이션 `b2c3d4e5f6a7`에서 **삭제**됨. 과제 재출제 필요.  
> 기획: `stage1-redesign-checklist.md`, `stage1-scoring-redesign.md`

## API

| Method | Path | 비고 |
|--------|------|------|
| POST | `/teacher/assignments/step1` | multipart: `question`, `answer`, defaults, `file`, `due_at` … |
| GET | `/student/assignments/{id}/step1` | 문제·자료텍스트·파라미터. 정답은 **마감 후**만 |
| POST | `/student/assignments/{id}/step1/chat` | 자유 `message` + 파라미터. chunk preview 포함 |
| POST | `/student/assignments/{id}/step1/submit` | `student_answer` + `final_parameters` |

### create Form
`class_id`, `subject`, `question`, `answer`, `due_at`, `default_chunk_size`, `default_top_k`, `default_temperature`, `file`

### submit Body
```json
{ "final_parameters": { "chunk_size", "top_k", "temperature" }, "student_answer": "..." }
```

### chat visualization
`total_chunks`, `retrieved_chunks`, `vector_search_score`, `retrieved_chunk_previews`, `approx_context_chars`

## 채점

- 제출 **2회** (`STAGE1_MAX_ATTEMPTS=2`)
- `final = max(0, correct_score − resource_penalty)`
  - 맞춤 → correct 100 / 틀림 → 0 (정규화 후 완전일치)
  - 리소스 감점: 교사 **default**보다 키운 `top_k`·`chunk_size`만 (`w=0.3`, 최대 ~30). temperature 제외
- 정답 문자열: 마감 전에는 API에 미포함

## PDF / OCR

- pypdf → (부족 시) Tesseract → OpenAI Vision
- 추출 후 `_normalize_extracted_text`로 URL·짧은 노이즈 줄 정리 → `documents.raw_text`
- create 시 preset 5종 청킹·임베딩 유지 (chat 시 재사용)

## Langflow

env: `LANGFLOW_URL`, `LANGFLOW_API_KEY`, `LANGFLOW_STAGE1_*`  
채팅은 힌트·근거 탐색용 (제출 본문 아님)
