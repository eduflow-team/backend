# Stage 1 백엔드 구현 메모

## API (`/api/v1`)

| Method | Path | 비고 |
|--------|------|------|
| POST | `/teacher/assignments/step1` | multipart + preset 5종 임베딩 (동시성 최대 2) |
| GET | `/student/assignments/{id}/step1` | 상세·시도·최고점 |
| POST | `/student/assignments/{id}/step1/chat` | 검색 + Langflow 생성 (+청크 preview). 미설정/실패 시 503 |
| POST | `/student/assignments/{id}/step1/submit` | 시도 3회 + 하이브리드 채점 + `student_prompt` |

Form (create): `class_id`, `subject`, `question`, `guideline`, `default_chunk_size`, `default_top_k`, `default_temperature`, `file`

submit Body: `final_parameters`, `selected_ai_response`, `student_prompt`

chat `rag_process_visualization`: `total_chunks`, `retrieved_chunks`, `vector_search_score`, `retrieved_chunk_previews`

---

## 파라미터 · 학습 목표

- 시작 default: `chunk_size=200`, `top_k=2`, `temperature=1.0` (부정확해지기 쉬운 시작점)
- **PDF마다 최적 조합이 다르다.** create 시 `optimal_parameters`를 서버가 찾아 저장
- 학생은 파라미터를 바꿔 보고, preview·답·채점으로 이 자료에 맞는 값(optimal에 가까운 값)을 찾는다
- 답변은 항상 존재 (거부 금지). 검색이 약하면 일반 지식 보완(틀린 답 가능), 관련 청크가 많으면 교재 우선

- PDF: `pypdf` 텍스트 레이어 추출 → 본문이 빈약하면 **OCR 폴백**
  - 1순위: Tesseract (`kor+eng`, Docker 이미지에 포함)
  - 2순위: OpenAI Vision (Tesseract 없을 때, `OPENAI_API_KEY` 필요)
- `question`은 업로드 PDF에 있는 주제로 둘 것.

---

## chat 검색·생성

- `top_k` / `temperature`만 바꿔도 재임베딩하지 않음
- DB preset 청크 로드 → 질문 임베딩 → cosine → `top_k` → Langflow 생성
- chunk_size 허용: `50 / 200 / 500 / 1200 / 3000` (밖이면 400)
- create 시 preset 5종 임베딩(동시 최대 2), chat은 재사용

## submit

- 마지막 제출만 `is_final=true`
- `student_prompt` = chat 때 `message` (고정 질문: `오늘 학습 주제의 내용을 전체적으로 알려줘`)
- 채점: **`최종 = 0.8×optimal근접 + 0.2×답변품질`**
  - `optimal_parameters`: create 시 서버가 자동 탐색해 DB 저장 (학생 API 미노출)
  - 근접: 제출 파라미터 ↔ optimal 정규화 거리 → `100×(1−distance)`
  - 품질: 제출 파라미터로 재검색한 청크 대비 답변 토큰 겹침 (기존과 동일)
- optimal 탐색: 고정 질문으로 chunk×top_k 검색 품질 그리드 → 최고점의 90% 이상(elbow) 중 **가장 약한** 설정 → temperature는 생성 가능 시 고품질 대역의 **가장 낮은** 값

## Langflow

`LangflowClient.run_stage1_chat` (Stage1 mock 없음)

- env: `LANGFLOW_URL`, `LANGFLOW_API_KEY`, `LANGFLOW_STAGE1_CHAT_FLOW_ID`, `LANGFLOW_STAGE1_PROMPT_NODE_ID`, `LANGFLOW_STAGE1_MODEL_NODE_ID`
- tweaks: Prompt `context`, OpenAI `temperature`
- Prompt `context`는 다른 노드와 연결하지 말 것 / Chat Input → `message` 유지
- 프롬프트: ai 레포 `prompts/stage1/rag-chat.md`

## 임베딩 안정화

- 실패 시 OpenAI HTTP status/body를 로그에 기록
- 429/5xx/timeout 등은 exponential backoff 재시도
- create preset 임베딩은 `Semaphore(2)`로 동시성 제한
