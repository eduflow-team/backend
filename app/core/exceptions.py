"""도메인 전용 예외 정의.

서비스 레이어는 이 예외들만 발생시키고, 실제 HTTP 응답 변환은
`app.core.error_handlers`에 등록된 전역 핸들러가 담당한다.
"""

from fastapi import status


class DomainException(Exception):
    """도메인 규칙 위반 시 발생하는 예외의 베이스 클래스."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "서버 내부 오류가 발생했습니다."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class InvalidSignupCodeError(DomainException):
    """교사 가입 인증 코드가 없거나 올바르지 않을 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "교사 가입 인증 코드가 올바르지 않습니다."


class EmailAlreadyExistsError(DomainException):
    """이미 가입된 이메일로 회원가입을 시도할 때 발생 (409)."""

    status_code = status.HTTP_409_CONFLICT
    default_message = "이미 존재하는 이메일입니다."


class InvalidCredentialsError(DomainException):
    """가입되지 않은 이메일이거나 비밀번호가 일치하지 않을 때 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "이메일 또는 비밀번호가 일치하지 않습니다."


class InvalidSocialTokenError(DomainException):
    """소셜 토큰이 만료됐거나 위조되어 검증에 실패했을 때 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "만료되었거나 유효하지 않은 소셜 토큰입니다."


class SocialAuthServiceUnavailableError(DomainException):
    """소셜 인증 서버(카카오/구글/애플)와의 통신에 실패했을 때 발생 (502)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_message = "소셜 인증 서버와의 통신에 실패했습니다."


class SocialAccountNotFoundError(DomainException):
    """소셜 토큰은 유효하나, 연동된 계정이 없을 때 발생 (404). 회원가입 유도용."""

    status_code = status.HTTP_404_NOT_FOUND
    default_message = "등록되지 않은 사용자입니다. 회원가입이 필요합니다."


class SocialAccountAlreadyExistsError(DomainException):
    """이미 연동된 소셜 계정(provider + social_id)으로 재가입을 시도할 때 발생 (409)."""

    status_code = status.HTTP_409_CONFLICT
    default_message = "이미 가입된 소셜 계정입니다."


class InvalidTokenError(DomainException):
    """Access Token이 없거나 서명이 유효하지 않거나 만료됐을 때 발생 (401).

    `/auth/logout`, `/auth/me`, `/auth/leave`가 공통으로 사용한다. (명세서상 문구가
    엔드포인트마다 조금씩 달랐으나, 의미가 동일해 하나로 통일함.)
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "인증 토큰이 유효하지 않거나 만료되었습니다."


class InvalidRefreshTokenError(DomainException):
    """POST /auth/refresh 전용: Refresh Token 서명 불일치·만료·재사용(RTR 위반) 시 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "Refresh Token이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요."


class DashboardAccessForbiddenError(DomainException):
    """학생/교사 전용 대시보드를 반대 role로 접근하려 할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "해당 대시보드에 접근할 권한이 없습니다."


class TeacherAssignmentAccessForbiddenError(DomainException):
    """교사용 과제 목록 API를 학생 role로 접근하려 할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "해당 과제 목록에 접근할 권한이 없습니다."


class TeacherAssignmentDeleteForbiddenError(DomainException):
    """교사용 과제 삭제 API를 권한 없는 계정으로 접근하려 할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "해당 과제를 삭제할 권한이 없습니다."


class AssignmentNotFoundError(DomainException):
    """존재하지 않거나 이미 삭제된 과제에 접근하려 할 때 발생 (404)."""

    status_code = status.HTTP_404_NOT_FOUND
    default_message = "존재하지 않거나 이미 삭제된 과제입니다."


class AttendanceAccessForbiddenError(DomainException):
    """출석 API를 role에 맞지 않는 계정으로 접근하려 할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "접근 권한이 없습니다."


class AttendanceUpdateForbiddenError(DomainException):
    """PATCH /teacher/attendance를 권한 없는 계정으로 호출할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "출석부를 수정할 권한이 없습니다."


class InvalidAttendanceUpdateError(DomainException):
    """PATCH /teacher/attendance 요청 바디가 명세와 맞지 않을 때 발생 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "수정할 출석 데이터의 형식이 올바르지 않습니다."


class NoticesAccessForbiddenError(DomainException):
    """학생 전용 공지 API를 role 불일치 계정으로 접근할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "접근 권한이 없습니다."


class TeacherNoticeCreateForbiddenError(DomainException):
    """교사용 공지 작성 API를 권한 없는 계정으로 접근할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "공지사항을 작성할 권한이 없습니다."


class InvalidNoticeCreateError(DomainException):
    """공지 작성 시 제목 또는 내용이 누락됐을 때 발생 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "공지사항의 제목이나 내용이 누락되었습니다."


class TeacherNoticeDeleteForbiddenError(DomainException):
    """교사용 공지 삭제 API를 권한 없는 계정으로 접근할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "공지사항을 삭제할 권한이 없습니다."


class NoticeNotFoundError(DomainException):
    """존재하지 않거나 이미 삭제된 공지에 접근할 때 발생 (404)."""

    status_code = status.HTTP_404_NOT_FOUND
    default_message = "존재하지 않거나 이미 삭제된 공지사항입니다."


class RecordsAccessForbiddenError(DomainException):
    """성적·기록 API를 role에 맞지 않는 계정으로 접근하려 할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "접근 권한이 없습니다."


class InvalidSearchKeywordError(DomainException):
    """검색 키워드가 누락되었거나 최소 길이 미만일 때 발생 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "검색 키워드가 누락되었거나 너무 짧습니다. (최소 2자 이상 입력)"


class SearchAccessForbiddenError(DomainException):
    """통합 검색 API를 STUDENT/TEACHER 외 role로 접근하려 할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "접근 권한이 없습니다."


class Stage1AccessForbiddenError(DomainException):
    """1단계 과제 API를 role·학급 권한이 없는 계정으로 접근할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "해당 과제에 접근할 권한이 없습니다."


class InvalidStage1ParameterError(DomainException):
    """1단계 chat/submit 파라미터가 누락되었거나 허용 범위를 넘을 때 발생 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "파라미터 허용 범위를 초과했습니다."


class InvalidStage1CreateError(DomainException):
    """1단계 과제 생성 시 필수 필드가 누락됐을 때 발생 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "필수 파라미터(문서 파일, 질문 등)가 누락되었습니다."


class UnsupportedStage1FileTypeError(DomainException):
    """지원하지 않는 문서 형식으로 1단계 과제를 생성할 때 발생 (415)."""

    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    default_message = "지원하지 않는 파일 형식입니다."


class Stage1FileTooLargeError(DomainException):
    """1단계 과제 문서 용량이 제한을 초과할 때 발생 (413)."""

    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_message = "파일 용량이 제한을 초과했습니다."


class Stage1DocumentProcessingError(DomainException):
    """문서 청크 분할·임베딩 처리 중 서버 오류가 발생했을 때 (500)."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "문서 청크 분할 및 벡터 임베딩 처리 중 서버 오류가 발생했습니다."


class Stage1SubmitLimitExceededError(DomainException):
    """1단계 제출 시도 횟수(3회)를 초과했을 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "최대 시도 횟수(3회)를 모두 소진하여 더 이상 제출할 수 없습니다."


class InvalidStage1SubmitError(DomainException):
    """1단계 제출 데이터가 누락되었거나 형식이 올바르지 않을 때 발생 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "제출 데이터가 누락되었거나 형식이 올바르지 않습니다."


class Stage2AccessForbiddenError(DomainException):
    """2단계 과제 API를 role·학급 권한이 없는 계정으로 접근할 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "접근 권한이 없습니다."


class InvalidStage2CreateError(DomainException):
    """2단계 과제 생성 시 필수 필드가 누락됐을 때 발생 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "필수 파라미터(문서 파일, 페르소나, 환각 타입 등)가 누락되었습니다."


class UnsupportedStage2FileTypeError(DomainException):
    """지원하지 않는 문서 형식으로 2단계 과제를 생성할 때 발생 (415)."""

    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    default_message = "지원하지 않는 파일 형식입니다."


class Stage2FileTooLargeError(DomainException):
    """2단계 과제 문서 용량이 제한을 초과할 때 발생 (413)."""

    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_message = "파일 용량이 제한을 초과했습니다."


class Stage2DocumentProcessingError(DomainException):
    """2단계 문서 텍스트 추출 중 서버 오류가 발생했을 때 (500)."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message = "서버 내부 오류가 발생했습니다."


class InvalidStage2HighlightError(DomainException):
    """2단계 하이라이트 제출 데이터가 누락되었거나 형식이 올바르지 않을 때 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = (
        "제출할 하이라이트 데이터(submissions)가 누락되었거나 형식이 올바르지 않습니다."
    )


class Stage2HighlightLimitExceededError(DomainException):
    """2단계 하이라이트 시도 횟수(5회)를 초과했을 때 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = (
        "최대 시도 횟수(5회)를 모두 소진하여 더 이상 과제를 제출할 수 없습니다."
    )


class InvalidStage2CorrectionError(DomainException):
    """2단계 correction 제출 데이터가 누락되었거나 형식이 올바르지 않을 때 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "제출할 정답 데이터(corrections)가 누락되었습니다."


class Stage2HighlightPhaseIncompleteError(DomainException):
    """하이라이트 단계 미완료 시 correction 제출 불가 (400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "하이라이트 단계를 먼저 완료해야 합니다."


class Stage2CorrectionAlreadySubmittedError(DomainException):
    """2단계 correction 이미 최종 제출 완료 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "이미 최종 정답을 제출하여 더 이상 수정할 수 없습니다."


class Stage2LangflowServiceUnavailableError(DomainException):
    """Langflow 2단계 생성 파이프라인 장애·타임아웃 시 발생 (503)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_message = (
        "AI 답변 생성 서비스에 일시적 장애가 발생했습니다. 잠시 후 다시 시도해 주세요."
    )
