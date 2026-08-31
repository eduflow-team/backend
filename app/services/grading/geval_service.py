"""G-Eval 湲곕컲 LLM-as-judge 梨꾩젏 (Langflow 誘몄궗??."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_REASONING_RUBRIC = """\
?됯? 湲곗?(reasoning_quality): ?숈깮??臾몄꽌 洹쇨굅瑜??ㅼ뼱 AI ?ㅻ쪟媛 ???섍컖?몄? ?ㅻ챸?덈뒗媛,
?좏깮???섍컖 ?좏삎怨??쇰━媛 留욌뒗媛.

?됯? ?④퀎:
1) student_reason??reference_document쨌evidence_sentence? ?곌껐?섎뒗媛
2) hallucination_reason怨??쇰━?곸쑝濡??쇱튂?섎뒗媛
3) student_error_type怨??ㅻ챸??留욌뒗媛
4) 1~5??遺??
?먯닔 媛?대뱶 (以뫢룰퀬??援먯쑁??:
- 5?? 臾몄꽌 洹쇨굅 ?몄슜 + ?섍컖 ?좏삎 + ?댁쑀媛 紐⑤몢 紐낇솗
- 4?? 洹쇨굅? ?좏삎? ??뱁븯???ㅻ챸???ㅼ냼 吏㏃쓬
- 3?? 洹쇨굅 ?먮뒗 ?좏삎 以??섎굹留?遺遺꾩쟻?쇰줈 留욎쓬
- 1~2?? 洹쇨굅 ?놁쓬 ?먮뒗 ?좏삎 遺덉씪移?
李멸퀬: ?섏씠?쇱씠???꾩튂? ?섍컖 ?좏삎? ?쒖뒪?쒖뿉???대? 留욌떎怨??먯젙?섏뿀?듬땲??
student_reason??evidence_sentence쨌hallucination_reason???쒖슜???쇰━瑜??ㅻ챸?덈뒗吏??吏묒쨷?섏꽭??
evidence_sentence媛 PDF 異붿텧 議곌컖?댁뼱??student_reason??洹??댁슜???몄슜쨌?곌껐?덈떎硫?4???댁긽??遺?ы븯?몄슂.
"""

_CORRECTION_RUBRIC = """\
?됯? 湲곗?:
- factual_accuracy: student_answer媛 correct_sentence쨌reference_document???ъ떎?곸쑝濡?遺?⑺븯?붽?
- completeness: original_highlight ?ㅻ쪟 援ш컙???섎???異⑸텇??援먯젙?섏뿀?붽?

?됯? ?④퀎:
1) student_answer媛 correct_sentence? **?섎????숈씪?섍굅???ы븿 愿怨?*?대㈃ factual_accuracy??4~5
2) student_answer媛 reference_document쨌evidence_sentence? 紐⑥닚?섏? ?딆쑝硫?factual_accuracy 媛??3) original_highlight???섎せ??二쇱옣???щ씪吏怨??щ컮瑜??ъ떎濡?諛붾뚯뿀?붿? completeness ?먮떒
4) factual_accuracy, completeness 媛곴컖 1~5 ?뺤닔 遺??
?먯닔 媛?대뱶 (以뫢룰퀬??援먯쑁??:
- factual_accuracy 5: correct_sentence? ?ъ떎쨌?쒗쁽??嫄곗쓽 媛숈쓬
- factual_accuracy 4: ?듭떖 ?ъ떎? 留욊퀬 ?쒗쁽留??ㅻ쫫
- factual_accuracy 3: ?쇰? 留욎쑝??以묒슂???ъ떎 ?꾨씫쨌?ㅻ쪟
- completeness 5: ?ㅻ쪟 援ш컙???꾩쟾??援먯젙??- completeness 4: ?듭떖 ?ㅻ쪟???쒓굅?섏뿀?쇰굹 遺???ㅻ챸??遺議?"""


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
                    "?섏씠?쇱씠?명븳 援ш컙???ㅻ쪟 ?꾩튂? 留욎? ?딆뒿?덈떎. "
                    "AI ?듬??먯꽌 臾몄꽌? ?ㅻⅨ ?쒗쁽???ㅼ떆 李얠븘蹂댁꽭??"
                ),
            )

        if not type_ok:
            return ReasoningEvaluation(
                reasoning_score=0.0,
                ai_feedback=(
                    "?섍컖 ?좏삎 ?좏깮??留욎? ?딆뒿?덈떎. "
                    "?섎Ⅴ?뚮굹 ?명뼢쨌?뺣낫 ?좎“쨌?섎せ??臾몄꽌 寃??以??대뼡 ?좏삎?몄? "
                    "?ㅼ떆 ?앷컖??蹂댁꽭??"
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
            'JSON留?異쒕젰: {"rating": 1-5 ?뺤닔, "feedback": "?쒓뎅??2~3臾몄옣"}'
        )
        parsed = await _request_geval_json(
            llm_config=llm_config,
            system_prompt="援먯쑁??梨꾩젏 judge. ?붿껌??JSON留?異쒕젰.",
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
        """LLM judge 誘몄꽕?????ㅼ썙??寃뱀묠 湲곕컲 異붿젙 (smoke test쨌濡쒖뺄??."""

        reason_tokens = _tokenize(student_reason)
        if len(reason_tokens) < 3:
            return ReasoningEvaluation(
                reasoning_score=0.2,
                ai_feedback=(
                    "?댁쑀 ?ㅻ챸???덈Т 吏㏃뒿?덈떎. 李멸퀬 臾몄꽌???대뼡 ?댁슜怨?"
                    "AI ?듬????ㅻⅨ吏 援ъ껜?곸쑝濡??곸뼱 蹂댁꽭??"
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
                "?꾨꼍?⑸땲?? ?먮낯 臾몄꽌???녿뒗 ?댁슜??媛쒖엯???섍컖???뺥솗??李얠븘?댁뀲怨? "
                "?섍컖 ?좏삎怨??댁쑀 ?ㅻ챸????뱁빀?덈떎."
            )
            return ReasoningEvaluation(reasoning_score=score, ai_feedback=feedback)

        coverage = reference_hits / max(len(reason_tokens), 1)
        alignment = reason_hits / max(len(_tokenize(hallucination_reason)), 1)
        raw = 0.55 * min(1.0, coverage * 2) + 0.45 * min(1.0, alignment * 2)
        rating = max(1, min(5, round(raw * 5)))
        if rating >= 5:
            score = 1.0
            feedback = (
                "?꾨꼍?⑸땲?? ?먮낯 臾몄꽌???녿뒗 ?댁슜??媛쒖엯???섍컖???뺥솗??李얠븘?댁뀲怨? "
                "?섍컖 ?좏삎怨??댁쑀 ?ㅻ챸????뱁빀?덈떎."
            )
        elif rating >= 4:
            score = 0.8
            feedback = (
                "臾몄꽌 洹쇨굅瑜??쇰? ?ㅼ뿀?듬땲?? ?대뼡 臾몄옣??AI ?듬?怨?"
                "???ㅻⅨ吏 ??臾몄옣 ??蹂댁셿??蹂댁꽭??"
            )
        else:
            score = round(rating / 5.0, 2)
            feedback = (
                "?댁쑀 ?ㅻ챸???꾩쭅 遺議깊빀?덈떎. 李멸퀬 臾몄꽌??洹쇨굅 臾몄옣???몄슜?섎ŉ "
                "????援ш컙???섍컖?몄? ?ㅻ챸??蹂댁꽭??"
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
                ai_feedback="臾몄꽌 洹쇨굅??留욊쾶 ?섏젙?섏뿀?듬땲??",
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
            'JSON留?異쒕젰: {"factual_accuracy": 1-5, "completeness": 1-5, '
            '"feedback": "?쒓뎅??1~2臾몄옣"}'
        )
        parsed = await _request_geval_json(
            llm_config=llm_config,
            system_prompt="援먯쑁??梨꾩젏 judge. ?붿껌??JSON留?異쒕젰.",
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
                ai_feedback="臾몄꽌 洹쇨굅??留욊쾶 ?섏젙?섏뿀?듬땲??",
            )

        answer_tokens = _tokenize(student_answer)
        if len(answer_tokens) < 2:
            return CorrectionEvaluation(
                factual_accuracy=1,
                completeness=1,
                ai_feedback="?섏젙 臾몄옣???덈Т 吏㏃뒿?덈떎. 臾몄꽌??留욊쾶 ??援ъ껜?곸쑝濡?怨좎퀜 蹂댁꽭??",
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
            feedback = "臾몄꽌 洹쇨굅??留욊쾶 ?섏젙?섏뿀?듬땲??"
        elif factual >= 4 and completeness >= 4:
            feedback = "臾몄꽌???덈뒗 ?댁슜?쇰줈 ?щ컮瑜닿쾶 怨좎낀?듬땲??"
        else:
            feedback = (
                "?섏젙 臾몄옣???꾩쭅 遺議깊빀?덈떎. 李멸퀬 臾몄꽌???쒗쁽??諛섏쁺??"
                "?ㅻ쪟 援ш컙?????뺥솗??怨좎퀜 蹂댁꽭??"
            )

        return CorrectionEvaluation(
            factual_accuracy=factual,
            completeness=completeness,
            ai_feedback=feedback,
        )


def resolve_geval_llm_config() -> GEvalLlmConfig | None:
    """G-Eval judge??OpenAI Chat Completions ?ㅼ젙??諛섑솚?쒕떎."""
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
        return "臾몄꽌 洹쇨굅??留욊쾶 ?섏젙?섏뿀?듬땲??"
    if factual < 4:
        return "?ъ떎 愿怨꾧? 臾몄꽌쨌?뺣떟怨?留욎? ?딆뒿?덈떎. 李멸퀬 臾몄꽌瑜??ㅼ떆 ?뺤씤??蹂댁꽭??"
    return "?ㅻ쪟 援ш컙??異⑸텇??援먯젙?섏? ?딆븯?듬땲?? ?섎?媛 ?꾩쟾??諛붾뚮룄濡??섏젙??蹂댁꽭??"


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
    return set(re.findall(r"[媛-?쥱-Za-z0-9]{2,}", (text or "").lower()))


def _count_hits(left: set[str], right: set[str]) -> int:
    return len(left & right)


def _default_feedback(rating: int) -> str:
    if rating >= 5:
        return (
            "?꾨꼍?⑸땲?? ?먮낯 臾몄꽌???녿뒗 ?댁슜??媛쒖엯???섍컖???뺥솗??李얠븘?댁뀲怨? "
            "?섍컖 ?좏삎怨??댁쑀 ?ㅻ챸????뱁빀?덈떎."
        )
    if rating >= 4:
        return "臾몄꽌 洹쇨굅瑜?議곌툑 ??援ъ껜?곸쑝濡??곕㈃ ??醫뗭뒿?덈떎."
    return "李멸퀬 臾몄꽌??洹쇨굅瑜??ㅼ뼱 ????몃뒗吏 ?ㅼ떆 ?ㅻ챸??蹂댁꽭??"
