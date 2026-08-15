"""Stage 2 external API contract regression tests (step 16).

Ensures internal generation pipeline changes do not alter the frontend-facing
request/response shapes, field names, or HTTP status codes.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.main import app
from app.models.assignment import Assignment
from app.models.document import Document
from app.models.enums import AssignmentPublishStatus, ProgressStatus
from app.models.stage import Stage2AssignmentDetail, Stage2ErrorAnswer
from app.models.student_status import StudentAssignmentStatus
from app.models.submission import Stage2HighlightSubmission
from app.models.user import User
from app.schemas.stage2 import (
    HallucinationTypeOption,
    Stage2AssignmentDetailResponse,
    Stage2AttemptsDetail,
    Stage2CreateResponse,
    Stage2GeneratedErrorItem,
    Step2CorrectionFeedbackDetail,
    Step2CorrectionItem,
    Step2CorrectionRequest,
    Step2CorrectionResponse,
    Step2HighlightEvaluationReport,
    Step2HighlightRequest,
    Step2HighlightResponse,
    Step2HighlightResultItem,
    Step2HighlightSubmissionItem,
)
from app.schemas.stage2_generation import Stage2GenerationMetadata
from app.services.grading.geval_service import CorrectionEvaluation, ReasoningEvaluation
from app.services.stage2_service import Stage2Service

# ---------------------------------------------------------------------------
# Frozen external contract (Notion flat JSON — do not change without FE sync)
# ---------------------------------------------------------------------------

CREATE_RESPONSE_FIELDS = frozenset(
    {
        "assignment_id",
        "title",
        "question",
        "flawed_ai_response",
        "expected_error_count",
        "generated_errors",
    }
)

GENERATED_ERROR_ITEM_FIELDS = frozenset(
    {
        "answer_id",
        "error_sentence",
        "error_type",
        "start_index",
        "end_index",
        "correct_sentence",
        "hallucination_reason",
        "evidence_sentence",
    }
)

DETAIL_RESPONSE_FIELDS = frozenset(
    {
        "assignment_id",
        "title",
        "reference_document_filename",
        "reference_document_url",
        "reference_document_text",
        "question",
        "flawed_ai_response",
        "expected_error_count",
        "hallucination_type_options",
        "hallucination_type_hints",
        "status",
        "highlight_phase_complete",
        "remaining_errors_to_find",
        "attempts",
        "cleared_highlights",
    }
)

HALLUCINATION_TYPE_OPTION_FIELDS = frozenset({"value", "label", "description"})
ATTEMPTS_DETAIL_FIELDS = frozenset({"max_attempts", "used_attempts", "remaining_attempts"})

HIGHLIGHT_REQUEST_FIELDS = frozenset({"submissions"})
HIGHLIGHT_SUBMISSION_ITEM_FIELDS = frozenset(
    {"highlighted_text", "student_error_type", "student_reason"}
)

HIGHLIGHT_RESPONSE_FIELDS = frozenset(
    {
        "is_all_correct",
        "highlight_phase_complete",
        "remaining_errors_to_find",
        "results",
        "attempts",
        "cleared_highlights",
    }
)

HIGHLIGHT_RESULT_ITEM_FIELDS = frozenset(
    {
        "highlighted_text",
        "student_error_type",
        "student_reason",
        "is_correct",
        "evaluation_report",
        "correct_answer",
        "correct_error_type",
    }
)

HIGHLIGHT_EVALUATION_REPORT_FIELDS = frozenset(
    {
        "location_match_score",
        "error_type_match",
        "reasoning_score",
        "ai_feedback",
    }
)

CORRECTION_REQUEST_FIELDS = frozenset({"corrections"})
CORRECTION_ITEM_FIELDS = frozenset({"original_highlight", "student_answer"})

CORRECTION_RESPONSE_FIELDS = frozenset(
    {
        "is_passed",
        "score",
        "final_correct_sentence",
        "feedback_details",
    }
)

CORRECTION_FEEDBACK_DETAIL_FIELDS = frozenset(
    {
        "student_found_error",
        "student_answer",
        "is_item_passed",
        "hallucination_reason",
        "reference_evidence",
        "ai_feedback",
    }
)

INTERNAL_GENERATION_FIELDS = frozenset(
    {
        "flow_version",
        "generation_attempts",
        "retrieval_source",
        "retrieved_context",
        "validation_codes",
        "candidate_chunk_ids",
    }
)

STEP2_OPENAPI_ROUTES: dict[tuple[str, str], int] = {
    ("post", "/teacher/assignments/step2"): 201,
    ("get", "/student/assignments/{id}/step2"): 200,
    ("post", "/student/assignments/{id}/step2/highlight"): 200,
    ("post", "/student/assignments/{id}/step2/correction"): 200,
}

STEP2_CREATE_FORM_FIELDS = frozenset(
    {
        "title",
        "subject",
        "question",
        "persona",
        "hallucination_types",
        "expected_error_count",
        "file",
    }
)

FLAWED_RESPONSE = (
    "장영실은 정말 뛰어난 발명가였어요. "
    "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요."
)
DOCUMENT_TEXT = (
    "장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.\n"
    "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다."
)
ERROR_SENTENCE = (
    "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요."
)


def _assert_fields(model_cls: type, expected: frozenset[str]) -> None:
    actual = set(model_cls.model_fields)
    assert actual == expected, (
        f"{model_cls.__name__} field mismatch.\n"
        f"  added: {sorted(actual - expected)}\n"
        f"  removed: {sorted(expected - actual)}"
    )


def _openapi_schema_names() -> dict[str, set[str]]:
    schema = app.openapi()
    return {
        name: set(definition.get("properties", {}).keys())
        for name, definition in schema.get("components", {}).get("schemas", {}).items()
    }


def _step2_path(method: str, suffix: str) -> str:
    return f"{settings.API_V1_STR.rstrip('/')}/{suffix.lstrip('/')}"


def _resolve_response_schema_ref(
    openapi: dict[str, Any], response_entry: dict[str, Any]
) -> str | None:
    content = response_entry.get("content") or {}
    json_content = content.get("application/json") or {}
    schema = json_content.get("schema") or {}
    ref = schema.get("$ref")
    if not ref:
        return None
    return ref.rsplit("/", 1)[-1]


def _build_service() -> Stage2Service:
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return Stage2Service(session)


def _student() -> User:
    return User(user_id=10, role="STUDENT", class_id=1)


def _assignment() -> Assignment:
    return Assignment(
        assignment_id=42,
        teacher_id=1,
        class_id=1,
        title="Stage 2 과제",
        stage=2,
        max_attempts=5,
        publish_status=AssignmentPublishStatus.PUBLISHED.value,
    )


def _detail() -> Stage2AssignmentDetail:
    return Stage2AssignmentDetail(
        detail_id=702,
        assignment_id=42,
        document_id=502,
        question="장영실의 발명품에 대해 설명해줘.",
        persona="페르소나",
        hallucinated_ai_answer=FLAWED_RESPONSE,
        hallucination_types=["PERSONA_BIAS", "RETRIEVAL_ERROR"],
        expected_error_count=1,
    )


def _error_answer() -> Stage2ErrorAnswer:
    return Stage2ErrorAnswer(
        answer_id=802,
        assignment_id=42,
        detail_id=702,
        error_sentence=ERROR_SENTENCE,
        error_type="RETRIEVAL_ERROR",
        start_index=10,
        end_index=60,
        correct_sentence="자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
        hallucination_reason="문서에 없는 서양 기술 주장",
        evidence_sentence="자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
    )


# ---------------------------------------------------------------------------
# Schema freeze tests
# ---------------------------------------------------------------------------


def test_external_schema_field_sets_are_frozen() -> None:
    _assert_fields(Stage2CreateResponse, CREATE_RESPONSE_FIELDS)
    _assert_fields(Stage2GeneratedErrorItem, GENERATED_ERROR_ITEM_FIELDS)
    _assert_fields(Stage2AssignmentDetailResponse, DETAIL_RESPONSE_FIELDS)
    _assert_fields(HallucinationTypeOption, HALLUCINATION_TYPE_OPTION_FIELDS)
    _assert_fields(Stage2AttemptsDetail, ATTEMPTS_DETAIL_FIELDS)
    _assert_fields(Step2HighlightRequest, HIGHLIGHT_REQUEST_FIELDS)
    _assert_fields(Step2HighlightSubmissionItem, HIGHLIGHT_SUBMISSION_ITEM_FIELDS)
    _assert_fields(Step2HighlightResponse, HIGHLIGHT_RESPONSE_FIELDS)
    _assert_fields(Step2HighlightResultItem, HIGHLIGHT_RESULT_ITEM_FIELDS)
    _assert_fields(Step2HighlightEvaluationReport, HIGHLIGHT_EVALUATION_REPORT_FIELDS)
    _assert_fields(Step2CorrectionRequest, CORRECTION_REQUEST_FIELDS)
    _assert_fields(Step2CorrectionItem, CORRECTION_ITEM_FIELDS)
    _assert_fields(Step2CorrectionResponse, CORRECTION_RESPONSE_FIELDS)
    _assert_fields(Step2CorrectionFeedbackDetail, CORRECTION_FEEDBACK_DETAIL_FIELDS)


def test_internal_generation_metadata_not_exposed_in_external_schemas() -> None:
    internal = set(Stage2GenerationMetadata.model_fields)
    assert INTERNAL_GENERATION_FIELDS <= internal

    external_models = (
        Stage2CreateResponse,
        Stage2GeneratedErrorItem,
        Stage2AssignmentDetailResponse,
        Step2HighlightResponse,
        Step2HighlightResultItem,
        Step2CorrectionResponse,
        Step2CorrectionFeedbackDetail,
    )
    for model_cls in external_models:
        leaked = internal & set(model_cls.model_fields)
        assert not leaked, f"{model_cls.__name__} exposes internal fields: {sorted(leaked)}"


def test_create_response_json_excludes_internal_fields() -> None:
    payload = Stage2CreateResponse(
        assignment_id=1,
        title="t",
        question="q",
        flawed_ai_response="a",
        expected_error_count=1,
        generated_errors=[
            Stage2GeneratedErrorItem(
                answer_id=1,
                error_sentence="e",
                error_type="PERSONA_BIAS",
                start_index=0,
                end_index=1,
                correct_sentence="c",
                hallucination_reason="h",
                evidence_sentence="v",
            )
        ],
    ).model_dump()
    assert INTERNAL_GENERATION_FIELDS.isdisjoint(payload.keys())
    assert INTERNAL_GENERATION_FIELDS.isdisjoint(payload["generated_errors"][0].keys())


# ---------------------------------------------------------------------------
# OpenAPI contract tests
# ---------------------------------------------------------------------------


def test_openapi_step2_routes_and_status_codes() -> None:
    openapi = app.openapi()
    paths = openapi["paths"]

    for (method, suffix), expected_status in STEP2_OPENAPI_ROUTES.items():
        path = _step2_path(method, suffix)
        assert path in paths, f"missing OpenAPI path: {path}"
        operation = paths[path][method]
        success_response = operation["responses"][str(expected_status)]
        assert success_response is not None
        assert _resolve_response_schema_ref(openapi, success_response) is not None


def test_openapi_step2_response_schemas_match_pydantic_models() -> None:
    schema_names = _openapi_schema_names()
    expected_pairs = {
        "Stage2CreateResponse": CREATE_RESPONSE_FIELDS,
        "Stage2AssignmentDetailResponse": DETAIL_RESPONSE_FIELDS,
        "Step2HighlightResponse": HIGHLIGHT_RESPONSE_FIELDS,
        "Step2CorrectionResponse": CORRECTION_RESPONSE_FIELDS,
    }
    for schema_name, expected_fields in expected_pairs.items():
        assert schema_name in schema_names, f"missing OpenAPI schema: {schema_name}"
        assert schema_names[schema_name] == expected_fields


def test_openapi_step2_request_schemas_match_pydantic_models() -> None:
    schema_names = _openapi_schema_names()
    assert schema_names["Step2HighlightRequest"] == HIGHLIGHT_REQUEST_FIELDS
    assert schema_names["Step2CorrectionRequest"] == CORRECTION_REQUEST_FIELDS


def test_openapi_step2_create_uses_multipart_form_fields() -> None:
    openapi = app.openapi()
    path = _step2_path("post", "/teacher/assignments/step2")
    operation = openapi["paths"][path]["post"]
    request_body = operation["requestBody"]
    content = request_body["content"]["multipart/form-data"]
    form_schema_name = content["schema"]["$ref"].rsplit("/", 1)[-1]
    form_fields = _openapi_schema_names()[form_schema_name]
    assert STEP2_CREATE_FORM_FIELDS <= form_fields


# ---------------------------------------------------------------------------
# Service response contract tests (mock persistence)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_detail_response_matches_external_contract() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_student())
    service.assignment_repository.get_by_id = AsyncMock(return_value=_assignment())
    service.stage2_detail_repository.get_by_assignment_id = AsyncMock(
        return_value=_detail()
    )
    service.document_repository.get_by_id = AsyncMock(
        return_value=Document(
            document_id=502,
            raw_text=DOCUMENT_TEXT,
            filename="stage2_doc.pdf",
            file_path="uploads/stage2/42/stage2_doc.pdf",
        )
    )
    service.status_repository.get_or_create = AsyncMock(
        return_value=StudentAssignmentStatus(
            user_id=10,
            assignment_id=42,
            progress_status=ProgressStatus.NOT_STARTED.value,
            remaining_attempts=5,
        )
    )
    service.highlight_repository.list_by_user_and_assignment = AsyncMock(return_value=[])
    service.stage2_error_answer_repository.list_by_assignment_id = AsyncMock(
        return_value=[_error_answer()]
    )

    response = await service.get_step2_assignment(10, 42)
    parsed = Stage2AssignmentDetailResponse.model_validate(response.model_dump())

    assert set(parsed.model_fields) == DETAIL_RESPONSE_FIELDS
    assert parsed.assignment_id == 42
    assert parsed.reference_document_filename == "stage2_doc.pdf"
    assert parsed.reference_document_url.endswith("/student/assignments/42/step2/document")
    assert parsed.expected_error_count == 1
    assert len(parsed.hallucination_type_options) == 3
    assert set(parsed.hallucination_type_options[0].model_fields) == (
        HALLUCINATION_TYPE_OPTION_FIELDS
    )
    assert set(parsed.attempts.model_fields) == ATTEMPTS_DETAIL_FIELDS
    assert INTERNAL_GENERATION_FIELDS.isdisjoint(parsed.model_dump().keys())


@pytest.mark.asyncio
async def test_get_reference_document_resolves_uploaded_file(tmp_path) -> None:
    upload_dir = tmp_path / "uploads" / "stage2" / "42"
    upload_dir.mkdir(parents=True)
    pdf_path = upload_dir / "stage2_doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_student())
    service.assignment_repository.get_by_id = AsyncMock(return_value=_assignment())
    service.stage2_detail_repository.get_by_assignment_id = AsyncMock(
        return_value=_detail()
    )
    service.document_repository.get_by_id = AsyncMock(
        return_value=Document(
            document_id=502,
            filename="stage2_doc.pdf",
            file_path=str(pdf_path),
        )
    )

    with patch("app.services.stage2_service._BACKEND_ROOT", tmp_path):
        path, filename, media_type = await service.get_step2_reference_document(10, 42)

    assert path == pdf_path
    assert filename == "stage2_doc.pdf"
    assert media_type == "application/pdf"


@pytest.mark.asyncio
async def test_highlight_response_matches_external_contract() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_student())
    service.assignment_repository.get_by_id = AsyncMock(return_value=_assignment())
    service.stage2_detail_repository.get_by_assignment_id = AsyncMock(
        return_value=_detail()
    )
    service.document_repository.get_by_id = AsyncMock(
        return_value=Document(document_id=502, raw_text=DOCUMENT_TEXT)
    )
    service.status_repository.get_or_create = AsyncMock(
        return_value=StudentAssignmentStatus(
            user_id=10,
            assignment_id=42,
            progress_status=ProgressStatus.IN_PROGRESS.value,
            remaining_attempts=4,
        )
    )
    service.status_repository.update_progress = AsyncMock()
    service.highlight_repository.list_by_user_and_assignment = AsyncMock(return_value=[])
    service.highlight_repository.create = AsyncMock(
        side_effect=lambda row: Stage2HighlightSubmission(
            highlight_id=901,
            user_id=row.user_id,
            assignment_id=row.assignment_id,
            highlighted_text=row.highlighted_text,
            start_index=row.start_index,
            end_index=row.end_index,
            error_type=row.error_type,
            highlight_score=row.highlight_score,
            is_correct=row.is_correct,
            feedback=row.feedback,
        )
    )
    service.stage2_error_answer_repository.list_by_assignment_id = AsyncMock(
        return_value=[_error_answer()]
    )
    service.geval_service.evaluate_reasoning = AsyncMock(
        return_value=ReasoningEvaluation(
            reasoning_score=0.98,
            ai_feedback="근거가 타당합니다.",
        )
    )

    payload = Step2HighlightRequest(
        submissions=[
            Step2HighlightSubmissionItem(
                highlighted_text=ERROR_SENTENCE,
                student_error_type="RETRIEVAL_ERROR",
                student_reason="문서에 없는 서양 기술 주장입니다.",
            )
        ]
    )
    response = await service.submit_highlight(10, 42, payload)
    parsed = Step2HighlightResponse.model_validate(response.model_dump())

    assert set(parsed.model_fields) == HIGHLIGHT_RESPONSE_FIELDS
    assert len(parsed.results) == 1
    result = parsed.results[0]
    assert set(result.model_fields) == HIGHLIGHT_RESULT_ITEM_FIELDS
    assert set(result.evaluation_report.model_fields) == HIGHLIGHT_EVALUATION_REPORT_FIELDS
    assert set(parsed.attempts.model_fields) == ATTEMPTS_DETAIL_FIELDS
    assert INTERNAL_GENERATION_FIELDS.isdisjoint(parsed.model_dump().keys())


@pytest.mark.asyncio
async def test_correction_response_matches_external_contract() -> None:
    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(return_value=_student())
    service.assignment_repository.get_by_id = AsyncMock(return_value=_assignment())
    service.stage2_detail_repository.get_by_assignment_id = AsyncMock(
        return_value=_detail()
    )
    service.document_repository.get_by_id = AsyncMock(
        return_value=Document(document_id=502, raw_text=DOCUMENT_TEXT)
    )
    service.submission_repository.get_final_by_user_and_assignment = AsyncMock(
        return_value=None
    )
    service.correction_repository.list_by_user_and_assignment = AsyncMock(return_value=[])
    service.highlight_repository.list_by_user_and_assignment = AsyncMock(
        return_value=[
            Stage2HighlightSubmission(
                highlight_id=901,
                user_id=10,
                assignment_id=42,
                highlighted_text=ERROR_SENTENCE,
                start_index=10,
                end_index=60,
                error_type="RETRIEVAL_ERROR",
                highlight_score=Decimal("1.00"),
                is_correct=True,
                feedback="ok",
            )
        ]
    )
    service.stage2_error_answer_repository.list_by_assignment_id = AsyncMock(
        return_value=[_error_answer()]
    )
    service.geval_service.evaluate_correction = AsyncMock(
        return_value=CorrectionEvaluation(
            factual_accuracy=5,
            completeness=5,
            ai_feedback="정확한 수정입니다.",
        )
    )
    service.submission_repository.create = AsyncMock(
        side_effect=lambda row: SubmissionStub(submission_id=1001, row=row)
    )
    service.correction_repository.create = AsyncMock()
    service.evaluation_repository.create = AsyncMock()
    service.highlight_repository.update = AsyncMock()
    service.status_repository.get_or_create = AsyncMock(
        return_value=StudentAssignmentStatus(
            user_id=10,
            assignment_id=42,
            progress_status=ProgressStatus.IN_PROGRESS.value,
            remaining_attempts=4,
        )
    )
    service.status_repository.update_progress = AsyncMock()

    payload = Step2CorrectionRequest(
        corrections=[
            Step2CorrectionItem(
                original_highlight=ERROR_SENTENCE,
                student_answer="자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
            )
        ]
    )
    response = await service.submit_correction(10, 42, payload)
    parsed = Step2CorrectionResponse.model_validate(response.model_dump())

    assert set(parsed.model_fields) == CORRECTION_RESPONSE_FIELDS
    assert len(parsed.feedback_details) == 1
    detail = parsed.feedback_details[0]
    assert set(detail.model_fields) == CORRECTION_FEEDBACK_DETAIL_FIELDS
    assert parsed.is_passed is True
    assert parsed.score == 100
    assert INTERNAL_GENERATION_FIELDS.isdisjoint(parsed.model_dump().keys())


class SubmissionStub:
    def __init__(self, submission_id: int, row: Any) -> None:
        self.submission_id = submission_id
        self.user_id = row.user_id
        self.assignment_id = row.assignment_id


@pytest.mark.asyncio
async def test_create_response_roundtrip_matches_external_contract() -> None:
    """Create contract: service output must round-trip through Stage2CreateResponse."""
    from app.schemas.stage2_generation import (
        Stage2GeneratedErrorDraft,
        Stage2LangflowGenerationResult,
        Stage2RetrievalInput,
    )
    from app.services.stage2_generation_orchestrator import Stage2GenerationPipelineResult
    from app.services.stage2_generation_validator import Stage2GenerationValidationResult
    from app.services.stage2_index_calculator import Stage2IndexApplicationResult

    service = _build_service()
    service.user_repository.get_by_id = AsyncMock(
        return_value=User(user_id=1, role="TEACHER", class_id=10)
    )

    error = Stage2GeneratedErrorDraft.model_validate(
        {
            "error_sentence": ERROR_SENTENCE,
            "error_type": "RETRIEVAL_ERROR",
            "start_index": 10,
            "end_index": 60,
            "correct_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다.",
            "hallucination_reason": "문서에 없는 서양 기술 주장",
            "evidence_sentence": "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
            "retrieval_source": "SAME_DOCUMENT",
            "retrieved_context": "distractor chunk",
        }
    )
    langflow_result = Stage2LangflowGenerationResult(
        flawed_ai_response=FLAWED_RESPONSE,
        generated_errors=[error],
    )
    pipeline = Stage2GenerationPipelineResult(
        result=langflow_result,
        retrieval_input=Stage2RetrievalInput(candidate_chunks=[]),
        validation=Stage2GenerationValidationResult(is_valid=True, codes=()),
        index_application=Stage2IndexApplicationResult(
            result=langflow_result,
            codes=(),
            applied=True,
        ),
        generation_attempts=1,
    )
    service.generation_orchestrator.generate = AsyncMock(return_value=pipeline)

    assignment = Assignment(assignment_id=42)
    document = Document(document_id=502)
    detail = Stage2AssignmentDetail(detail_id=702)
    error_row = Stage2ErrorAnswer(
        answer_id=802,
        error_sentence=error.error_sentence,
        error_type=error.error_type,
        start_index=error.start_index,
        end_index=error.end_index,
        correct_sentence=error.correct_sentence,
        hallucination_reason=error.hallucination_reason,
        evidence_sentence=error.evidence_sentence,
    )

    service.assignment_repository.create = AsyncMock(return_value=assignment)
    service.document_repository.create = AsyncMock(return_value=document)
    service.stage2_detail_repository.create = AsyncMock(return_value=detail)
    service.stage2_detail_repository.set_generation_metadata = AsyncMock(
        return_value=detail
    )
    service.stage2_error_answer_repository.create = AsyncMock(return_value=error_row)

    upload = AsyncMock()
    upload.filename = "lesson.txt"
    upload.read = AsyncMock(return_value=DOCUMENT_TEXT.encode("utf-8"))

    with patch(
        "app.services.stage2_service.extract_text_from_upload",
        return_value=DOCUMENT_TEXT,
    ):
        response = await service.create_step2_assignment(
            1,
            title="Stage 2",
            subject="과학",
            question="장영실의 발명품에 대해 설명해줘.",
            persona="페르소나",
            hallucination_types_raw='["RETRIEVAL_ERROR"]',
            expected_error_count=1,
            file=upload,
        )

    parsed = Stage2CreateResponse.model_validate(response.model_dump())
    assert set(parsed.model_fields) == CREATE_RESPONSE_FIELDS
    assert set(parsed.generated_errors[0].model_fields) == GENERATED_ERROR_ITEM_FIELDS
    dumped = parsed.model_dump()
    assert INTERNAL_GENERATION_FIELDS.isdisjoint(dumped.keys())
    assert INTERNAL_GENERATION_FIELDS.isdisjoint(dumped["generated_errors"][0].keys())
    assert "retrieval_source" not in dumped["generated_errors"][0]
    assert "retrieved_context" not in dumped["generated_errors"][0]
