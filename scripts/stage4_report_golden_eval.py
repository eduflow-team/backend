#!/usr/bin/env python3
"""Stage4 보고서 골든셋 평가 — 이중 검증.

1) intent_band  (품질): 카테고리별 교육적 기대 점수 대역
2) regression_lock (회귀): 대표 샘플만 좁은 점수(±1) 잠금

사용법 (backend 루트):
    python3 scripts/stage4_report_golden_eval.py

골든셋: ../ai/docs-local/calibration/report-golden-set.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.grading.stage4_grader import (  # noqa: E402
    Stage4Grader,
    Stage4ReportInput,
)

CANDIDATES = [
    ROOT.parent / "ai" / "docs-local" / "calibration" / "report-golden-set.json",
    Path("/ai/docs-local/calibration/report-golden-set.json"),
]


def _resolve_golden_path() -> Path:
    for path in CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "골든셋 없음. 기대한 경로: " + ", ".join(str(p) for p in CANDIDATES)
    )


def main() -> None:
    golden_path = _resolve_golden_path()
    data = json.loads(golden_path.read_text(encoding="utf-8"))
    samples = data["samples"]
    intent_bands: dict = data.get("intent_bands") or {}
    grader = Stage4Grader()

    intent_fails: list[str] = []
    lock_fails: list[str] = []
    pass_fails: list[str] = []
    missing_band: list[str] = []

    print(f"=== Stage4 Report Golden Eval (v{data.get('version', '?')}) ===")
    print(f"path: {golden_path}")
    print(
        f"mode: intent_band(품질) + regression_lock(회귀, "
        f"n={sum(1 for s in samples if 'regression_lock' in s)})\n"
    )

    if not intent_bands:
        print("ERROR: intent_bands 없음 — 품질 검증 불가")
        sys.exit(2)

    for s in samples:
        r = s["report"]
        report = Stage4ReportInput(
            successful_attacks=r["successful_attacks"],
            failed_attacks=r["failed_attacks"],
            why_breached=r["why_breached"],
            defense_ideas=r["defense_ideas"],
        )
        result = grader.evaluate_report(
            report=report,
            attempts_used_at_clear=s.get("attempts_used_at_clear", 4),
            max_attempts=s.get("max_attempts", 10),
            difficulty=s.get("difficulty", "NORMAL"),
        )

        analysis = result.analysis_score
        cat = s.get("category")
        checks: list[tuple[str, bool, str]] = []

        # 1) 의도 대역 (품질) — 전 샘플
        band = intent_bands.get(cat) if cat else None
        if band is None:
            missing_band.append(s["id"])
            checks.append(("intent", False, f"no band for category={cat}"))
        else:
            lo, hi = int(band["min"]), int(band["max"])
            ok_intent = lo <= analysis <= hi
            checks.append(
                (
                    "intent",
                    ok_intent,
                    f"{lo}..{hi}" + ("" if ok_intent else f" got={analysis}"),
                )
            )
            if not ok_intent:
                intent_fails.append(s["id"])

        # 2) 회귀 락 — 대표 샘플만
        if "regression_lock" in s:
            lo = int(s["regression_lock"]["min"])
            hi = int(s["regression_lock"]["max"])
            ok_lock = lo <= analysis <= hi
            checks.append(
                (
                    "lock",
                    ok_lock,
                    f"{lo}..{hi}" + ("" if ok_lock else f" got={analysis}"),
                )
            )
            if not ok_lock:
                lock_fails.append(s["id"])

        # 3) 통과 여부 (선택)
        if "expected_pass" in s:
            ok_pass = result.is_passed == s["expected_pass"]
            checks.append(("pass", ok_pass, ""))
            if not ok_pass:
                pass_fails.append(s["id"])

        ok = all(c for _, c, _ in checks)
        status = "PASS" if ok else "FAIL"
        detail = " ".join(
            f"{name}={'OK' if c else 'NG'}({extra})" if extra else f"{name}={'OK' if c else 'NG'}"
            for name, c, extra in checks
        )
        print(f"[{status}] {s['id']}  category={cat}")
        print(
            f"  analysis={analysis} total={result.current_score} "
            f"clear={result.clear_score} eff={result.efficiency_score}"
        )
        print(f"  checks: {detail}")
        if not ok:
            print(f"  breakdown={result.analysis_breakdown}")
            if band:
                print(f"  intent_why={band.get('why', '')}")
        print()

    n_fail = len(set(intent_fails + lock_fails + pass_fails + missing_band))
    print(f"samples={len(samples)} fails={n_fail}")
    print(f"  intent_band fails : {len(intent_fails)}" + (f" {intent_fails}" if intent_fails else ""))
    print(f"  regression fails  : {len(lock_fails)}" + (f" {lock_fails}" if lock_fails else ""))
    print(f"  expected_pass fails: {len(pass_fails)}" + (f" {pass_fails}" if pass_fails else ""))
    if missing_band:
        print(f"  missing intent_band: {missing_band}")

    if n_fail == 0:
        print("ALL PASSED (intent + regression)")
    else:
        print("SOME FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
