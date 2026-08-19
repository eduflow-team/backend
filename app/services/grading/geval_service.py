"""G-Eval 기반 LLM-as-judge 채점 (Langflow 미사용)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_REASONING_RUBRIC = """\
평가 기준(reasoning_quality): 학생이 문서 근거를 들어 AI 오류가 왜 환각인지 설명했는가,
선택한 환각 유형과 논리가 맞는가.

평가 단계:
1) student_reason이 reference_document·evidence_sentence와 연결되는가
2) hallucination_reason과 논리적으로 일치하는가
3) student_error_type과 설명이 맞는가
4) 1~5점 부여

점수 가이드 (중·고등 교육용):
- 5점: 문서 근거 인용 + 환각 유형 + 이유가 모두 명확
- 4점: 근거와 유형은 타당하나 설명이 다소 짧음
- 3점: 근거 또는 유형 중 하나만 부분적으로 맞음
- 1~2점: 근거 없음 또는 유형 불일치

참고: 하이라이트 위치와 환각 유형은 시스템에서 이미 맞다고 판정되었습니다.
student_reason이 evidence_sentence·hallucination_reason을 활용해 논리를 설명했는지에 집중하세요.
evidence_sentence가 PDF 추출 조각이어도 student_reason이 그 내용을 인용·연결했다면 4점 이상을 부여하세요.
"""

_CORRECTION_RUBRIC = """\
평가 기준:
- factual_accuracy: student_answer가 correct_sentence·reference_document에 사실적으로 부합하는가
- completeness: original_highlight 오류 구간이 의미상 충분히 교정되었는가

평가 단계:
1) student_answer가 correct_sentence와 **의미상 동일하거나 포함 관계**이면 factual_accuracy는 4~5
2) student_answer가 reference_document·evidence_sentence와 모순되지 않으면 factual_accuracy 가산
3) original_highlight의 잘못된 주장이 사라지고 올바른 사실로 바뀌었는지 completeness 판단
4) factual_accuracy, completeness 각각 1~5 정수 부여

점수 가이드 (중·고등 교육용):
- factual_accuracy 5: correct_sentence와 사실·표현이 거의 같음
- factual_accuracy 4: 핵심 사실은 맞고 표현만 다름
- factual_accuracy 3: 일부 맞으나 중요한 사실 누락·오류
- completeness 5: 오류 구간이 완전히 교정됨
- completeness 4: 핵심 오류는 제거되었으나 부연 설명이 부족
"""


@dataclass(frozen=True)
class ReasoningEvaluation:
    reasoning_score: float
    ai_feedback: str


@dataclass(frozen=True)
class CorrectionEvaluation:
    factual_accuracy: int
    completeness: int
    ai_feedback: str

    @property
    def is_item_passed(self) -> bool:
        return (
            self.factual_accuracy >= settings.STAGE2_CORRECTION_MIN_SCORE
            and self.completeness >= settings.STAGE2_CORRECTION_MIN_SCORE
        )


@dataclass(frozen=True)
class GEvalLlmConfig:
    chat_completions_url: str
    api_key: str
    model: str


class GEvalService:
    async def evaluate_reasoning(
        self,
        *,
        student_reason: str,
        student_error_type: str,
        hallucination_reason: str,
        evidence_sentence: str,
        reference_document: str,
        location_ok: bool,
        type_ok: bool,
    ) -> ReasoningEvaluation:
        if not location_ok:
            return ReasoningEvaluation(
                reasoning_score=0.0,
                ai_feedback=(
                    "하이라이트한 구간이 오류 위치와 맞지 않습니다. "
                    "AI 답변에서 문서와 다른 표현을 다시 찾아보세요."
                ),
            )

        if not type_ok:
            return ReasoningEvaluation(
                reasoning_score=0.0,
                ai_feedback=(
                    "환각 유형 선택이 맞지 않습니다. "
                    "페르소나 편향·정보 날조·잘못된 문서 검색 중 어떤 유형인지 "
                    "다시 생각해 보세요."
                ),
            )

        llm_config = resolve_geval_llm_config()
        if llm_config is not None:
            try:
                evaluation = await self._evaluate_reasoning_llm(
                    llm_config=llm_config,
                    student_reason=student_reason,
                    student_error_type=student_error_type,
                    hallucination_reason=hallucination_reason,
                    evidence_sentence=evidence_sentence,
                    reference_document=reference_document,
                )
            except Exception:  # noqa: BLE001
                logger.exception("G-Eval reasoning failed; using fallback")
                evaluation = self._evaluate_reasoning_fallback(
                    student_reason=student_reason,
                    hallucination_reason=hallucination_reason,
                    evidence_sentence=evidence_sentence,
                    reference_document=reference_document,
                )
        else:
            evaluation = self._evaluate_reasoning_fallback(
                student_reason=student_reason,
                hallucination_reason=hallucination_reason,
                evidence_sentence=evidence_sentence,
                reference_document=reference_document,
            )

        return _finalize_reasoning_evaluation(
            evaluation,
            student_reason=student_reason,
            student_error_type=student_error_type,
            hallucination_reason=hallucination_reason,
            evidence_sentence=evidence_sentence,
        )

    async def _evaluate_reasoning_llm(
        self,
        *,
        llm_config: GEvalLlmConfig,
        student_reason: str,
        student_error_type: str,
        hallucination_reason: str,
        evidence_sentence: str,
        reference_document: str,
    ) -> ReasoningEvaluation:
        doc_preview = (reference_document or "")[:1500]
        prompt = (
            f"{_REASONING_RUBRIC}\n\n"
            f"student_error_type: {student_error_type}\n"
            f"student_reason: {student_reason}\n"
            f"hallucination_reason: {hallucination_reason}\n"
            f"evidence_sentence: {evidence_sentence}\n"
            f"reference_document:\n{doc_preview}\n\n"
            'JSON만 출력: {"rating": 1-5 정수, "feedback": "한국어 2~3문장"}'
        )
        parsed = await _request_geval_json(
            llm_config=llm_config,
            system_prompt="교육용 채점 judge. 요청한 JSON만 출력.",
            user_prompt=prompt,
        )
        rating = max(1, min(5, int(parsed.get("rating", 1))))
        feedback = str(parsed.get("feedback", "")).strip() or _default_feedback(rating)
        return ReasoningEvaluation(
            reasoning_score=round(rating / 5.0, 2),
            ai_feedback=feedback,
        )

    def _evaluate_reasoning_fallback(
        self,
        *,
        student_reason: str,
        hallucination_reason: str,
        evidence_sentence: str,
        reference_document: str,
    ) -> ReasoningEvaluation:
        """LLM judge 미설정 시 키워드 겹침 기반 추정 (smoke test·로컬용)."""

        reason_tokens = _tokenize(student_reason)
        if len(reason_tokens) < 3:
            return ReasoningEvaluation(
                reasoning_score=0.2,
                ai_feedback=(
                    "이유 설명이 너무 짧습니다. 참고 문서의 어떤 내용과 "
                    "AI 답변이 다른지 구체적으로 적어 보세요."
                ),
            )

        reference_hits = _count_hits(
            reason_tokens,
            _tokenize(reference_document) | _tokenize(evidence_sentence),
        )
        reason_hits = _count_hits(reason_tokens, _tokenize(hallucination_reason))

        if reference_hits >= 2 and len(reason_tokens) >= 5 and (
            reason_hits >= 1 or reference_hits >= 3
        ):
            score = 1.0
            feedback = (
                "완벽합니다! 원본 문서에 없는 내용이 개입된 환각을 정확히 찾아내셨고, "
                "환각 유형과 이유 설명도 타당합니다."
            )
            return ReasoningEvaluation(reasoning_score=score, ai_feedback=feedback)

        coverage = reference_hits / max(len(reason_tokens), 1)
        alignment = reason_hits / max(len(_tokenize(hallucination_reason)), 1)
        raw = 0.55 * min(1.0, coverage * 2) + 0.45 * min(1.0, alignment * 2)
        rating = max(1, min(5, round(raw * 5)))
        if rating >= 5:
            score = 1.0
            feedback = (
                "완벽합니다! 원본 문서에 없는 내용이 개입된 환각을 정확히 찾아내셨고, "
                "환각 유형과 이유 설명도 타당합니다."
            )
        elif rating >= 4:
            score = 0.8
            feedback = (
                "문서 근거를 일부 들었습니다. 어떤 문장이 AI 답변과 "
                "왜 다른지 한 문장 더 보완해 보세요."
            )
        else:
            score = round(rating / 5.0, 2)
            feedback = (
                "이유 설명이 아직 부족합니다. 참고 문서의 근거 문장을 인용하며 "
                "왜 이 구간이 환각인지 설명해 보세요."
            )

        return ReasoningEvaluation(reasoning_score=score, ai_feedback=feedback)

    async def evaluate_correction(
        self,
        *,
        student_answer: str,
        correct_sentence: str,
        original_highlight: str,
        reference_document: str,
        hallucination_reason: str,
        evidence_sentence: str,
    ) -> CorrectionEvaluation:
        if _answers_equivalent(student_answer, correct_sentence):
            return CorrectionEvaluation(
                factual_accuracy=5,
                completeness=5,
                ai_feedback="문서 근거에 맞게 수정되었습니다.",
            )

        llm_config = resolve_geval_llm_config()
        if llm_config is not None:
            try:
                return await self._evaluate_correction_llm(
                    llm_config=llm_config,
                    student_answer=student_answer,
                    correct_sentence=correct_sentence,
                    original_highlight=original_highlight,
                    reference_document=reference_document,
                    hallucination_reason=hallucination_reason,
                    evidence_sentence=evidence_sentence,
                )
            except Exception:  # noqa: BLE001
                logger.exception("G-Eval correction failed; using fallback")

        return self._evaluate_correction_fallback(
            student_answer=student_answer,
            correct_sentence=correct_sentence,
            reference_document=reference_document,
            evidence_sentence=evidence_sentence,
        )

    async def _evaluate_correction_llm(
        self,
        *,
        llm_config: GEvalLlmConfig,
        student_answer: str,
        correct_sentence: str,
        original_highlight: str,
        reference_document: str,
        hallucination_reason: str,
        evidence_sentence: str,
    ) -> CorrectionEvaluation:
        doc_preview = (reference_document or "")[:1500]
        prompt = (
            f"{_CORRECTION_RUBRIC}\n\n"
            f"original_highlight: {original_highlight}\n"
            f"student_answer: {student_answer}\n"
            f"correct_sentence: {correct_sentence}\n"
            f"hallucination_reason: {hallucination_reason}\n"
            f"evidence_sentence: {evidence_sentence}\n"
            f"reference_document:\n{doc_preview}\n\n"
            'JSON만 출력: {"factual_accuracy": 1-5, "completeness": 1-5, '
            '"feedback": "한국어 1~2문장"}'
        )
        parsed = await _request_geval_json(
            llm_config=llm_config,
            system_prompt="교육용 채점 judge. 요청한 JSON만 출력.",
            user_prompt=prompt,
        )
        factual = max(1, min(5, int(parsed.get("factual_accuracy", 1))))
        completeness = max(1, min(5, int(parsed.get("completeness", 1))))
        if _answers_equivalent(student_answer, correct_sentence):
            factual = 5
            completeness = 5
        feedback = str(parsed.get("feedback", "")).strip() or _correction_feedback(
            factual, completeness
        )
        return CorrectionEvaluation(
            factual_accuracy=factual,
            completeness=completeness,
            ai_feedback=feedback,
        )

    def _evaluate_correction_fallback(
        self,
        *,
        student_answer: str,
        correct_sentence: str,
        reference_document: str,
        evidence_sentence: str,
    ) -> CorrectionEvaluation:
        normalized_answer = re.sub(r"\s+", " ", student_answer.strip().lower())
        normalized_correct = re.sub(r"\s+", " ", correct_sentence.strip().lower())
        if (
            normalized_answer == normalized_correct
            or normalized_answer in normalized_correct
            or normalized_correct in normalized_answer
        ):
            return CorrectionEvaluation(
                factual_accuracy=5,
                completeness=5,
                ai_feedback="문서 근거에 맞게 수정되었습니다.",
            )

        answer_tokens = _tokenize(student_answer)
        if len(answer_tokens) < 2:
            return CorrectionEvaluation(
                factual_accuracy=1,
                completeness=1,
                ai_feedback="수정 문장이 너무 짧습니다. 문서에 맞게 더 구체적으로 고쳐 보세요.",
            )

        correct_hits = _count_hits(answer_tokens, _tokenize(correct_sentence))
        doc_hits = _count_hits(
            answer_tokens,
            _tokenize(reference_document) | _tokenize(evidence_sentence),
        )
        factual = max(1, min(5, round((correct_hits / max(len(_tokenize(correct_sentence)), 1)) * 5)))
        completeness = max(1, min(5, round((doc_hits / max(len(answer_tokens), 1)) * 5)))

        if correct_hits >= 2 and doc_hits >= 2:
            factual = 5
            completeness = 5
            feedback = "문서 근거에 맞게 수정되었습니다."
        elif factual >= 4 and completeness >= 4:
            feedback = "문서에 있는 내용으로 올바르게 고쳤습니다."
        else:
            feedback = (
                "수정 문장이 아직 부족합니다. 참고 문서의 표현을 반영해 "
                "오류 구간을 더 정확히 고쳐 보세요."
            )

        return CorrectionEvaluation(
            factual_accuracy=factual,
            completeness=completeness,
            ai_feedback=feedback,
        )


def resolve_geval_llm_config() -> GEvalLlmConfig | None:
    """G-Eval judge용 OpenAI Chat Completions 설정을 반환한다."""
    if not settings.OPENAI_API_KEY.strip():
        return None
    return GEvalLlmConfig(
        chat_completions_url="https://api.openai.com/v1/chat/completions",
        api_key=settings.OPENAI_API_KEY.strip(),
        model=settings.OPENAI_CHAT_MODEL,
    )


async def _request_geval_json(
    *,
    llm_config: GEvalLlmConfig,
    system_prompt: str,
    user_prompt: str,
    timeout: float = 120.0,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if llm_config.api_key:
        headers["Authorization"] = f"Bearer {llm_config.api_key}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            llm_config.chat_completions_url,
            headers=headers,
            json={
                "model": llm_config.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )
    return _parse_json_content(content)


def _finalize_reasoning_evaluation(
    evaluation: ReasoningEvaluation,
    *,
    student_reason: str,
    student_error_type: str,
    hallucination_reason: str,
    evidence_sentence: str,
) -> ReasoningEvaluation:
    if not _qualifies_for_structured_reasoning_pass(
        student_reason=student_reason,
        student_error_type=student_error_type,
        hallucination_reason=hallucination_reason,
        evidence_sentence=evidence_sentence,
    ):
        return evaluation
    return ReasoningEvaluation(
        reasoning_score=max(
            evaluation.reasoning_score,
            settings.STAGE2_REASONING_THRESHOLD,
        ),
        ai_feedback=evaluation.ai_feedback,
    )


def _qualifies_for_structured_reasoning_pass(
    *,
    student_reason: str,
    student_error_type: str,
    hallucination_reason: str,
    evidence_sentence: str,
) -> bool:
    reason = student_reason.strip()
    if len(reason) < 25:
        return False
    if student_error_type not in reason:
        return False

    evidence = evidence_sentence.strip()
    if evidence:
        compact_reason = re.sub(r"\s+", "", reason.lower())
        compact_evidence = re.sub(r"\s+", "", evidence.lower())
        if len(compact_evidence) >= 6:
            prefix = compact_evidence[: min(12, len(compact_evidence))]
            if prefix not in compact_reason and compact_evidence not in compact_reason:
                return False

    hall_tokens = _tokenize(hallucination_reason)
    reason_tokens = _tokenize(reason)
    if hall_tokens and not (hall_tokens & reason_tokens):
        return False
    return True


def _answers_equivalent(left: str, right: str) -> bool:
    normalized_left = re.sub(r"\s+", " ", left.strip().lower())
    normalized_right = re.sub(r"\s+", " ", right.strip().lower())
    if not normalized_left or not normalized_right:
        return False
    return (
        normalized_left == normalized_right
        or normalized_left in normalized_right
        or normalized_right in normalized_left
    )


def _correction_feedback(factual: int, completeness: int) -> str:
    if factual >= 4 and completeness >= 4:
        return "문서 근거에 맞게 수정되었습니다."
    if factual < 4:
        return "사실 관계가 문서·정답과 맞지 않습니다. 참고 문서를 다시 확인해 보세요."
    return "오류 구간이 충분히 교정되지 않았습니다. 의미가 완전히 바뀌도록 수정해 보세요."


def _parse_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[가-힣A-Za-z0-9]{2,}", (text or "").lower()))


def _count_hits(left: set[str], right: set[str]) -> int:
    return len(left & right)


def _default_feedback(rating: int) -> str:
    if rating >= 5:
        return (
            "완벽합니다! 원본 문서에 없는 내용이 개입된 환각을 정확히 찾아내셨고, "
            "환각 유형과 이유 설명도 타당합니다."
        )
    if rating >= 4:
        return "문서 근거를 조금 더 구체적으로 쓰면 더 좋습니다."
    return "참고 문서의 근거를 들어 왜 틀렸는지 다시 설명해 보세요."
