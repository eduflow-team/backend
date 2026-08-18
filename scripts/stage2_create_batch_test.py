"""Stage2 teacher create batch test (generation only, no student/G-Eval)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BASE = "/api/v1"
ROOT = os.getenv("TEST_BASE_URL", "http://localhost:8000")
TEACHER_CODE = os.getenv("TEACHER_SIGNUP_CODE", "TEACHER_SECRET_CODE")
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "2027 수능특강 동아시아사-excerpt.pdf"
)
RUN_COUNT = int(os.getenv("STAGE2_BATCH_RUN_COUNT", "30"))


@dataclass
class RunResult:
    run_index: int
    upload_name: str
    status_code: int
    elapsed_sec: float
    assignment_id: int | None = None
    error_detail: str = ""


@dataclass
class BatchSummary:
    results: list[RunResult] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.results if item.status_code == 201)

    @property
    def failure_count(self) -> int:
        return len(self.results) - self.success_count


def resolve_fixture() -> Path:
    env_path = os.getenv("STAGE2_TEST_FIXTURE", "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_FIXTURE


def signup_teacher(api: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    classes = httpx.get(f"{api}/auth/classes", timeout=30.0)
    if classes.status_code != 200:
        raise RuntimeError(f"classes status={classes.status_code}")

    class_id = classes.json()["classes"][0]["class_id"]
    teacher_email = f"s2batch-t-{suffix}@example.com"
    password = "S2Batch123!"

    signup = httpx.post(
        f"{api}/auth/signup",
        json={
            "email": teacher_email,
            "name": "S2BatchTeacher",
            "phone": "010-5555-6666",
            "password": password,
            "role": "TEACHER",
            "class_id": class_id,
            "signup_code": TEACHER_CODE,
        },
        timeout=30.0,
    )
    if signup.status_code != 201:
        raise RuntimeError(f"signup status={signup.status_code} body={signup.text[:300]}")

    login = httpx.post(
        f"{api}/auth/login",
        json={"email": teacher_email, "password": password},
        timeout=30.0,
    )
    if login.status_code != 200:
        raise RuntimeError(f"login status={login.status_code}")
    return login.json()["access_token"]


def run_create(
    api: str,
    token: str,
    *,
    run_index: int,
    fixture: Path,
    content: bytes,
) -> RunResult:
    upload_name = f"batch-run-{run_index:03d}.pdf"
    started = time.perf_counter()
    response = httpx.post(
        f"{api}/teacher/assignments/step2",
        headers={"Authorization": f"Bearer {token}"},
        data={
            "title": f"Stage2 batch run {run_index:03d}",
            "subject": os.getenv("STAGE2_TEST_SUBJECT", "hist"),
            "question": os.getenv(
                "STAGE2_TEST_QUESTION",
                "명·청 교역과 관련된 내용을 설명해줘.",
            ),
            "persona": os.getenv(
                "STAGE2_TEST_PERSONA",
                "청과의 교역을 과도하게 미화하는 역사 선생님",
            ),
            "hallucination_types": json.dumps(
                [
                    value.strip().upper()
                    for value in os.getenv(
                        "STAGE2_TEST_HALLUCINATION_TYPES",
                        "PERSONA_BIAS,INFORMATION_FABRICATION",
                    ).split(",")
                    if value.strip()
                ],
                ensure_ascii=False,
            ),
            "expected_error_count": os.getenv("STAGE2_TEST_EXPECTED_ERROR_COUNT", "1"),
        },
        files={"file": (upload_name, content, "application/pdf")},
        timeout=300.0,
    )
    elapsed_sec = time.perf_counter() - started

    assignment_id = None
    error_detail = ""
    if response.status_code == 201:
        assignment_id = response.json().get("assignment_id")
    else:
        try:
            error_detail = response.json().get("detail", response.text[:200])
        except Exception:  # noqa: BLE001
            error_detail = response.text[:200]

    return RunResult(
        run_index=run_index,
        upload_name=upload_name,
        status_code=response.status_code,
        elapsed_sec=elapsed_sec,
        assignment_id=assignment_id,
        error_detail=str(error_detail),
    )


def parse_log_metrics(log_text: str) -> dict[str, dict[str, object]]:
    """Map batch upload filename -> generation_attempts / failure_codes."""
    metrics: dict[str, dict[str, object]] = {}
    current_file: str | None = None

    started_re = re.compile(
        r"stage2 generation started .* filename=(batch-run-\d{3}\.pdf)"
    )
    attempt_re = re.compile(
        r"stage2 generation attempt .* attempt=(\d+) max_attempts=(\d+) "
        r"duration_ms=[\d.]+ failure_codes=([^ ]+) will_retry=(True|False)"
    )
    succeeded_re = re.compile(
        r"stage2 generation succeeded .* assignment_id=(\d+) generation_attempts=(\d+)"
    )
    failed_re = re.compile(
        r"stage2 generation failed .* generation_attempts=(\d+) failure_codes=([^\s]+)"
    )

    for line in log_text.splitlines():
        started_match = started_re.search(line)
        if started_match:
            current_file = started_match.group(1)
            metrics.setdefault(current_file, {"attempts": [], "outcome": None})
            continue

        if current_file is None:
            continue

        attempt_match = attempt_re.search(line)
        if attempt_match:
            metrics[current_file]["attempts"].append(
                {
                    "attempt": int(attempt_match.group(1)),
                    "max_attempts": int(attempt_match.group(2)),
                    "failure_codes": attempt_match.group(3),
                    "will_retry": attempt_match.group(4) == "True",
                }
            )
            continue

        succeeded_match = succeeded_re.search(line)
        if succeeded_match:
            metrics[current_file]["outcome"] = {
                "status": "success",
                "assignment_id": int(succeeded_match.group(1)),
                "generation_attempts": int(succeeded_match.group(2)),
            }
            current_file = None
            continue

        failed_match = failed_re.search(line)
        if failed_match:
            metrics[current_file]["outcome"] = {
                "status": "failed",
                "generation_attempts": int(failed_match.group(1)),
                "failure_codes": failed_match.group(2),
            }
            current_file = None

    return metrics


def print_summary(summary: BatchSummary, log_metrics: dict[str, dict[str, object]]) -> None:
    total = len(summary.results)
    success = summary.success_count
    failure = summary.failure_count
    success_rate = (success / total * 100) if total else 0.0

    attempt_on_success: list[int] = []
    failure_code_counter: dict[str, int] = {}
    durations_success: list[float] = []
    durations_failure: list[float] = []

    print("=" * 72)
    print("Stage2 CREATE BATCH SUMMARY")
    print("=" * 72)
    print(f"runs={total} success={success} failure={failure} success_rate={success_rate:.1f}%")
    print()

    print(f"{'run':>4}  {'status':>6}  {'sec':>6}  {'attempts':>8}  {'failure_codes':<30}  assignment_id")
    print("-" * 72)
    for item in summary.results:
        log_info = log_metrics.get(item.upload_name, {})
        outcome = log_info.get("outcome") or {}
        attempts = outcome.get("generation_attempts", "-")
        failure_codes = outcome.get("failure_codes", "-")
        if item.status_code == 201:
            durations_success.append(item.elapsed_sec)
            if isinstance(attempts, int):
                attempt_on_success.append(attempts)
        else:
            durations_failure.append(item.elapsed_sec)
            if isinstance(failure_codes, str) and failure_codes != "-":
                for code in failure_codes.split(","):
                    failure_code_counter[code] = failure_code_counter.get(code, 0) + 1

        print(
            f"{item.run_index:4d}  {item.status_code:6d}  {item.elapsed_sec:6.1f}  "
            f"{str(attempts):>8}  {str(failure_codes):<30}  {item.assignment_id or '-'}"
        )

    print()
    if attempt_on_success:
        ones = sum(1 for value in attempt_on_success if value == 1)
        twos = sum(1 for value in attempt_on_success if value == 2)
        print(
            "successful generation_attempts: "
            f"1st_try={ones} 2nd_try={twos} "
            f"(of {len(attempt_on_success)} successes)"
        )
    if failure_code_counter:
        print("failure_codes (failed runs):")
        for code, count in sorted(failure_code_counter.items(), key=lambda x: -x[1]):
            print(f"  - {code}: {count}")
    if durations_success:
        print(
            "elapsed_sec success: "
            f"min={min(durations_success):.1f} "
            f"avg={sum(durations_success)/len(durations_success):.1f} "
            f"max={max(durations_success):.1f}"
        )
    if durations_failure:
        print(
            "elapsed_sec failure: "
            f"min={min(durations_failure):.1f} "
            f"avg={sum(durations_failure)/len(durations_failure):.1f} "
            f"max={max(durations_failure):.1f}"
        )
    print("=" * 72)


def maybe_sync_langflow_flow() -> None:
    if os.getenv("STAGE2_SYNC_LANGFLOW", "1").strip().lower() in {"0", "false", "no"}:
        return
    sync_script = Path(__file__).resolve().parent / "patch_langflow_stage2_from_repo.py"
    if not sync_script.exists():
        return
    import subprocess

    print("syncing Langflow stage2 flow from repo...")
    subprocess.run([sys.executable, str(sync_script)], check=False)


def main() -> None:
    maybe_sync_langflow_flow()
    fixture = resolve_fixture()
    if not fixture.exists():
        print(f"FAIL: fixture missing: {fixture}")
        sys.exit(1)

    content = fixture.read_bytes()
    api = f"{ROOT.rstrip('/')}{BASE}"

    print(f"fixture={fixture}")
    print(f"runs={RUN_COUNT}")
    print(f"api={api}")
    print("mode=create-only (no highlight/correction, no G-Eval calls from this script)")
    print()

    token = signup_teacher(api)
    summary = BatchSummary()

    for run_index in range(1, RUN_COUNT + 1):
        print(f"[{run_index}/{RUN_COUNT}] creating...", flush=True)
        result = run_create(
            api,
            token,
            run_index=run_index,
            fixture=fixture,
            content=content,
        )
        summary.results.append(result)
        print(
            f"[{run_index}/{RUN_COUNT}] status={result.status_code} "
            f"elapsed={result.elapsed_sec:.1f}s "
            f"assignment_id={result.assignment_id or '-'}",
            flush=True,
        )

    log_metrics: dict[str, dict[str, object]] = {}
    log_file = os.getenv("STAGE2_BATCH_LOG_FILE", "").strip()
    if not log_file:
        default_log = Path(__file__).resolve().parent / "stage2_batch_logs_after.txt"
        if default_log.exists():
            log_file = str(default_log)
    if log_file:
        log_metrics = parse_log_metrics(Path(log_file).read_text(encoding="utf-8", errors="replace"))

    print_summary(summary, log_metrics)

    json_path = os.getenv(
        "STAGE2_BATCH_RESULT_JSON",
        str(Path(__file__).resolve().parent / "stage2_create_batch_results.json"),
    )
    Path(json_path).write_text(
        json.dumps(
            {
                "fixture": str(fixture),
                "run_count": RUN_COUNT,
                "success_count": summary.success_count,
                "failure_count": summary.failure_count,
                "results": [item.__dict__ for item in summary.results],
                "log_metrics": log_metrics,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved: {json_path}")

    if summary.failure_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
