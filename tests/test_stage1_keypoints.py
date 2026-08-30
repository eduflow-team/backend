"""Stage1 키포인트 채점 단위 테스트."""

from app.services.assignment_service import AssignmentService


def test_grade_keypoints_partial_and_full():
    keypoints = ["토지 조사 사업", "산미 증식 계획", "무단 통치"]
    partial = AssignmentService._grade_keypoints(
        "일제강점기에는 토지 조사 사업과 산미 증식 계획이 있었다.",
        keypoints,
    )
    assert partial["matched_keypoints"] == 2
    assert partial["total_keypoints"] == 3
    assert partial["correct_score"] == 67
    assert partial["is_correct"] is False

    full = AssignmentService._grade_keypoints(
        "1) 토지조사사업\n2) 산미증식계획\n3) 무단통치로 저항을 억압했다.",
        keypoints,
    )
    assert full["matched_keypoints"] == 3
    assert full["correct_score"] == 100
    assert full["is_correct"] is True


def test_normalize_keypoints_json_and_lines():
    assert AssignmentService._normalize_keypoints(
        '["A", "B", "C"]'
    ) == ["A", "B", "C"]
    assert AssignmentService._normalize_keypoints("A\nB\nC") == ["A", "B", "C"]


def test_redact_unmatched_keypoints_before_reveal():
    from app.schemas.assignments import Stage1KeypointResult

    results = [
        Stage1KeypointResult(index=1, keypoint="토지 조사 사업", matched=True),
        Stage1KeypointResult(index=2, keypoint="산미 증식 계획", matched=False),
    ]
    redacted = AssignmentService._redact_keypoint_results_for_student(
        results, revealed=False
    )
    assert redacted[0].keypoint == "토지 조사 사업"
    assert redacted[1].keypoint == ""
    shown = AssignmentService._redact_keypoint_results_for_student(
        results, revealed=True
    )
    assert shown[1].keypoint == "산미 증식 계획"
