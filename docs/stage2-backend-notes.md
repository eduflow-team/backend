# Stage 2 백엔드 구현 메모

> **외부 API(Notion flat JSON)는 변경하지 않는다.**  
> 프론트가 사용하는 4개 엔드포인트·필드명·HTTP 상태 코드는 그대로 유지한다.

## 구현된 API (`/api/v1`)

| Method | Path | Status | 비고 |
|--------|------|--------|------|
| POST | `/teacher/assignments/step2` | 201 | multipart, Langflow 생성 후 DB 저장 |
| GET | `/student/assignments/{id}/step2` | 200 | 상세·문서·시도·cleared_highlights |
| POST | `/student/assignments/{id}/step2/highlight` | 200 | 하이브리드 채점 |
| POST | `/student/assignments/{id}/step2/correction` | 200 | G-Eval 수정문 채점, 최종 제출 1회 |

Form 필드: `title`, `subject`, `question`, `persona`, `hallucination_types`(JSON 배열 문자열), `expected_error_count`, `file`

생성 실패(검증·Langflow 오류) 시 **503**, DB에 과제를 저장하지 않는다.

---

## 생성 파이프라인 (plan-first v2)

교사 과제 생성 시 내부 흐름:

```text
PDF 업로드 → source_text 추출
  → 질문 관련 excerpt 생성 (resolve_stage2_document_context)
  → 청크 후보 생성 (build_stage2_chunk_candidates, 전체 source 기준)
  → Langflow 호출 (Planner → EXAONE → Formatter, generation_text 사용)
  → 생성 결과 검증 (validate_stage2_generation_result)
  → 품질 Gate (슬롯·정답 노출·추가 오류 등)
  → start_index / end_index 서버 계산 (apply_server_error_indices)
  → 성공 시에만 DB 저장 + generation_metadata 기록
  → 실패 시 validation_feedback으로 최대 1회 재시도
  → 최종 실패 시 503 (저장 없음)
```

긴 PDF는 `STAGE2_GENERATION_DOCUMENT_MAX_CHARS`(기본 6000)를 넘으면 질문 relevance 기준으로 발췌한 excerpt만 Langflow·validator·학생 `reference_document_text`에 사용한다. 원본 PDF 파일은 디스크에 그대로 보관한다.

주요 모듈:

| 모듈 | 역할 |
|------|------|
| `stage2_document_context.py` | 질문 기준 excerpt (`generation_text`) 결정 |
| `Stage2GenerationOrchestrator` | 청크 후보 → Langflow → 검증 → 인덱스 → 재시도 |
| `stage2_generation_validator.py` | 구조·근거·유형·품질 검증 |
| `stage2_response_quality.py` | 슬롯 잔존, 정답 암시/노출, 유사 추가 오류 탐지 |
| `stage2_index_calculator.py` | `error_sentence` 기준 인덱스 서버 계산 |
| `stage2_chunk_candidates.py` | PDF 청크 후보 (유사도·다양성) |
| `stage2_retrieval_input.py` | Langflow Planner용 `candidate_chunks` 직렬화 |
| `LangflowClient.run_stage2_hallucination` | Flow 호출·내부 스키마 파싱 |

Langflow 출력은 **내부 스키마**(`app/schemas/stage2_generation.py`)로 파싱하고,  
저장·API 응답은 **외부 스키마**(`app/schemas/stage2.py`)만 사용한다.

---

## 환각 유형 정의

| value | 의미 |
|-------|------|
| `PERSONA_BIAS` | 페르소나의 잘못된 믿음으로 답변 왜곡 |
| `INFORMATION_FABRICATION` | 문서·근거 어디에도 없는 사실을 모델이 생성 |
| `RETRIEVAL_ERROR` | 잘못 검색·연결된 청크를 근거로 오류 생성 |

`RETRIEVAL_ERROR`는 `retrieval_source`(`SAME_DOCUMENT` / `SYNTHETIC`)와 `retrieved_context`가 필요하다.

---

## Retrieval 후보 (1 → 2 fallback)

1. **SAME_DOCUMENT**: 업로드 PDF를 청크로 나누고, 질문과 유사한 distractor 후보 3~5개를 Langflow Planner에 전달
2. **SYNTHETIC**: 적절한 후보가 없으면 AI Flow에서 synthetic distractor 생성

전략 상수: `SAME_DOCUMENT_THEN_SYNTHETIC` (`Stage2RetrievalInput`)

청크 제한: `STAGE2_CHUNK_SIZE`, `STAGE2_MAX_CHUNK_CANDIDATES`, `STAGE2_MAX_CANDIDATE_TOTAL_CHARS`

---

## 검증 규칙

### 구조 검증

- `generated_errors` 개수 = `expected_error_count`
- `error_type` ∈ 교사가 선택한 `hallucination_types`
- 오류 개수 ≥ 허용 유형 수이면 **선택한 모든 유형**이 최소 1회 포함
- 필수 문자열 비어 있지 않음, 중복 `error_sentence` 없음
- `error_sentence` ⊂ `flawed_ai_response`
- `evidence_sentence` ⊂ PDF `document_text` (유사도 ≥ `STAGE2_LOCATION_THRESHOLD`)
- `RETRIEVAL_ERROR` → `retrieved_context` + `retrieval_source` 필수

### 인덱스 계산 (서버 책임)

LLM이 준 `start_index`/`end_index`는 **무시**한다.

```text
flawed_ai_response에서 error_sentence 검색
  → 0회: ERROR_SENTENCE_NOT_FOUND
  → 2회 이상: ERROR_SENTENCE_AMBIGUOUS
  → 1회: start_index, end_index 확정
```

### 품질 Gate (학생용 답변)

- `SLOT_MARKER_REMAINING`: `[[ERROR_N]]` 슬롯 표기 잔존
- `ANSWER_LEAKAGE_DETECTED`: "잘못 이해", "사실이 아니" 등 오류 암시
- `CORRECT_ANSWER_EXPOSED`: `correct_sentence`가 정상 문장으로 노출
- `UNLABELED_ERROR_DUPLICATE`: 슬롯 밖 유사 오류 문장 추가

검증 실패 코드는 `Stage2GenerationValidationCode` enum으로 반환한다.

---

## 재시도 정책

| 항목 | 값 |
|------|-----|
| 최대 시도 | `STAGE2_GENERATION_MAX_ATTEMPTS` (기본 **2** = 최초 1 + 재시도 1) |
| 재시도 대상 | 검증·인덱스·품질 Gate 실패 |
| 재시도 제외 | Langflow transport/파싱 오류 (`LANGFLOW_UNAVAILABLE`) |
| 피드백 | 실패 코드 → `validation_feedback` 문자열 → Planner 재호출 |
| 청크 후보 | 최초 1회 생성 후 재시도 시 **재사용** |

최종 실패: `Stage2LangflowServiceUnavailableError` → HTTP **503**, DB rollback.

---

## generation_metadata (내부, 외부 API 미노출)

`stage2_assignment_details.generation_metadata` (JSON):

```json
{
  "flow_version": "stage2-v2",
  "generation_attempts": 1,
  "retrieval_source": "SAME_DOCUMENT",
  "retrieved_context": "...",
  "validation_codes": [],
  "candidate_chunk_ids": ["chunk-1", "chunk-2"]
}
```

감사·재현용. 프론트 응답·Notion API 명세에는 포함하지 않는다.

---

## Langflow 연동

환경변수:

- `LANGFLOW_URL`, `LANGFLOW_API_KEY`, `LANGFLOW_STAGE2_FLOW_ID`
- `LANGFLOW_STAGE2_GEN_PROMPT_NODE_ID`, `LANGFLOW_STAGE2_EXT_PROMPT_NODE_ID`
- `STAGE2_FLOW_VERSION` (기본 `stage2-v2`)

`LANGFLOW_STAGE2_FLOW_ID`가 비어 있으면 mock 응답.

Flow 상세·노드 ID: `ai/docs/stage2-langflow-contract.md`, `ai/flows/stage2-hallucination-gen.json`

---

## 저장 트랜잭션 (검증 성공 시)

1. `assignments` (stage=2, class_id=교사 `users.class_id`, max_attempts=5)
2. `documents` (raw_text, 벡터화 생략)
3. `stage2_assignment_details` (+ `generation_metadata`)
4. `stage2_error_answers`

실패 시 `assignments`/`documents`/`stage2_*` **저장하지 않음**, 업로드 파일도 rollback.

---

## Highlight 채점 (`HighlightGrader` + `GEvalService`)

- **Rule-based**: `location_match_score` ≥ 0.8, `error_type` exact match
- **G-Eval**: `student_reason` → `reasoning_score` (θ_R ≥ 0.95)
- **판정**: 3조건 AND → `is_correct`
- `OPENAI_API_KEY` 없으면 G-Eval fallback(키워드 겹침) — smoke test용
- G-Eval judge: `OPENAI_API_KEY` + `OPENAI_CHAT_MODEL` (기본 `gpt-4o-mini`)

## Correction 채점 (`GEvalService`)

- 선행: `highlight_phase_complete=true`, `corrections.length` = `expected_error_count`
- **G-Eval**: `factual_accuracy` + `completeness` 각 ≥ 4/5 (`STAGE2_CORRECTION_MIN_SCORE`)
- 저장: `submissions`(is_final), `stage2_correction_submissions`, `evaluations`, `student_assignment_status` COMPLETED
- **1회성** 재제출 → 403

---

## 환경변수 요약

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `STAGE2_GENERATION_MAX_ATTEMPTS` | 2 | 생성 재시도 상한 |
| `STAGE2_LOCATION_THRESHOLD` | 0.8 | 위치·근거 유사도 |
| `STAGE2_REASONING_THRESHOLD` | 0.95 | 하이라이트 reasoning |
| `STAGE2_CORRECTION_MIN_SCORE` | 4 | 수정문 G-Eval 통과 점수 |
| `OPENAI_CHAT_MODEL` | gpt-4o-mini | Stage2 G-Eval judge 모델 |
| `STAGE2_MAX_ATTEMPTS` | 5 | 학생 하이라이트 시도 횟수 |
| `STAGE2_CHUNK_SIZE` | 400 | PDF 청크 크기 |
| `STAGE2_MAX_CHUNK_CANDIDATES` | 5 | Langflow 전달 후보 수 |
| `STAGE2_GENERATION_DOCUMENT_MAX_CHARS` | 6000 | Langflow/학생 참고문서 excerpt 상한 |

---

## 테스트

```bash
# 단위·통합 (DB/Langflow 불필요)
pytest -q

# API 계약 회귀 (step 16)
pytest tests/test_stage2_api_contract.py -q

# E2E (backend + Langflow + DB 필요)
# 기본 fixture: scripts/fixtures/stage2_doc.txt
# PDF 예: $env:STAGE2_TEST_FIXTURE="scripts/fixtures/your.pdf"
python scripts/stage2_e2e_test.py
```

주요 테스트 파일:

| 파일 | 내용 |
|------|------|
| `test_stage2_generation_validator.py` | 검증 규칙 |
| `test_stage2_generation_orchestrator.py` | 재시도·오케스트레이션 |
| `test_stage2_generation_integration.py` | mock Langflow 통합 |
| `test_stage2_api_contract.py` | 외부 API 필드·OpenAPI 고정 |
| `test_stage2_e2e_validation.py` | create 응답 E2E 검증 헬퍼 |

---

## 후속 작업 (이번 PR 범위外)

- **G-Eval baseline·임계값 검증** (step 18): reasoning/correction 임계값 실측 조정
- **Langflow 가용성**: 연속 호출 시 간헐적 503 — infra/timeout 별도 대응
- **파인튜닝 검토** (step 19): Flow+검증 후에도 품질 부족 시 골드 데이터 수집

---

## 카드형 세트 출제 (정책 변경 · 구현 체크리스트)

**정책:** 과제 1장 = 환각 **1개** (`expected_error_count=1`). 학생은 카드(과제) 여러 장.  
**학생 API 4개·필드명·Notion `API 명세서 (1)`는 변경하지 않는다** (배열 필드는 길이 0~1로 사용).  
**DB 수정:** [`stage2-db-upgrade.md`](stage2-db-upgrade.md) (`assignments.set_id`, `publish_status`만 추가).

### 바꾸지 않음

| 항목 | 비고 |
|------|------|
| `GET/POST .../step2` (detail, highlight, correction, document) | 스키마 동일 |
| Highlight / Correction 채점 (`HighlightGrader`, `GEvalService`) | 장당 1회 플로우 |
| Langflow / `ai` Flow | 호출 시 `expected_error_count=1`, `hallucination_types` 1개 |
| DB `stage2_*` 테이블 | 세트 묶음은 선택(아래) |

### 백엔드 구현 (우선순위)

| # | 작업 | 설명 |
|---|------|------|
| 1 | **세트 생성 API** | `POST /teacher/assignments/step2/set` (multipart). PDF·질문·페르소나 1회, `card_count` 1~5, `hallucination_types` 체크박스(배열). |
| 2 | **카드별 생성 루프** | PDF 파싱·`chunk_candidates` **1회** → 카드마다 `expected_error_count=1`, 유형 **로테이션**(체크한 유형 순환). 기존 `create_step2_assignment` 로직 재사용. |
| 3 | **초안·배포 상태** | 생성 직후 `DRAFT`, 교사 선택 후 `PUBLISHED` (또는 `assignments` 플래그/`stage2_set` 테이블). 학생 detail은 **PUBLISHED만** 노출. |
| 4 | **세트 조회·선택** | `GET /teacher/assignments/step2/set/{set_id}` — 후보 카드 미리보기(`flawed_ai_response`, `error_type`, `generated_errors` 교사용). `PATCH`로 포함 카드 ID 목록 확정·배포. |
| 5 | **단건 create 정리** | 기존 `POST .../step2` 유지하되 `expected_error_count` **1만 허용**하거나, 세트 API만 노출 (팀 선택). |
| 6 | **학생 목록** | 기존 `GET /student/dashboard/assignments` + `stage=2` 필터로 카드 목록 (신규 API 없이 MVP 가능). |
| 7 | **테스트·스크립트** | E2E·batch 기본값 `expected_error_count=1`. 세트 생성·부분 실패·배포 통합 테스트 추가. |

### 생성 시간·동시성

- 카드 N장 = Langflow **N회** (순차 권장, 진행률 `2/N` 응답).
- 병렬 3은 인프라 여유 시 선택 (`STAGE2_SET_PARALLELISM`).

### 프론트 (참고, backend 범위外)

- 교사: 카드 수 드롭다운(1~5), 유형 체크박스, 미리보기·체크·배포.
- 학생: `stage2-verify.html` / React — **1환각·1카드** UI (진행 0/1, 교정 1칸).

### AI 레포

- **필수 변경 없음** (`expected_error_count=1` 이미 지원).

