"""명령행 진입점.

  python -m idphoto gate  photo1.jpg photo2.jpg
  python -m idphoto run   photo*.jpg --spec id_kr --n 12 --out out/order
  python -m idphoto check result.jpg
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

from .config import DEFAULT
from .detect import FaceAnalyzer
from .gating import evaluate as gate_eval
from .pipeline import Pipeline
from .keys import KeyUnavailable, acquire
from .provenance import read_disclosure
from .specs import SPECS

_LEVEL = {"ok": "✓", "warn": "!", "reject": "✗"}


def _load(paths: list[str]):
    out = []
    for p in paths:
        img = cv2.imread(p)
        if img is None:
            print(f"  읽기 실패: {p}", file=sys.stderr)
            continue
        out.append((p, img))
    return out


def cmd_gate(args) -> int:
    analyzer = FaceAnalyzer()
    usable = 0
    for path, img in _load(args.photos):
        res = gate_eval(img, analyzer.analyze(img), DEFAULT.gate)
        usable += res.usable
        head = "사용 가능" if res.usable else "사용 불가"
        print(f"\n{Path(path).name}  [{head}]  점수 {res.score:.2f}")
        for c in res.checks:
            print(f"   {_LEVEL[c.level]} {c.label:12s} {c.value:9.2f}")
        for m in res.coaching():
            print(f"   → {m}")
    print(f"\n사용 가능 {usable}/{len(args.photos)}장")
    return 0 if usable else 1


def cmd_run(args) -> int:
    loaded = _load(args.photos)
    if not loaded:
        print("읽을 수 있는 사진이 없습니다", file=sys.stderr)
        return 1

    if args.provider != "mock":
        # 키는 ai_keys 프로토콜로만 받는다 — 파일을 직접 읽지 않는다.
        try:
            src = acquire(args.provider, purpose=args.purpose,
                          est_usd=args.est_usd, model=args.model,
                          approval=args.approval)
        except KeyUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"키 출처: {src}", file=sys.stderr)

    presets = None
    if args.wardrobe or args.backdrop:
        from . import prompts
        presets = prompts.grid(
            [args.wardrobe] if args.wardrobe else None,
            [args.backdrop] if args.backdrop else None)

    pipe = Pipeline(provider=args.provider, model=args.model)
    try:
        res = pipe.run([img for _, img in loaded], spec_key=args.spec,
                       n_generate=args.n, n_present=args.present,
                       retouch=args.retouch, seed=args.seed, presets=presets)
    except ValueError as exc:
        print(f"중단: {exc}", file=sys.stderr)
        return 1

    summary = res.summary()
    if res.usage:
        summary["usage"] = res.usage
        summary["est_usd_next_run"] = round(
            res.cost_usd / max(1, summary["generated"]) * args.n, 4)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n선발 결과")
    for rank, c in enumerate(res.selected, 1):
        fr = c.framing
        print(f"  {rank}. {c.variant_id}  점수 {c.score:.3f}  유사도 {c.id_cos:.3f}  "
              f"머리 {fr.head_mm:.1f}mm  {c.preset['wardrobe']}/{c.preset['backdrop']}")

    if res.candidates and not res.selected:
        print("\n통과한 후보가 없습니다. 탈락 사유:")
        for c in res.candidates[:8]:
            print(f"  - {c.variant_id}: {c.rejected}")

    if args.out:
        for p in pipe.deliver(res, args.out, preview=args.preview):
            print(f"  저장 {p}")
    return 0


def cmd_check(args) -> int:
    for path in args.photos:
        rec = read_disclosure(path)
        print(f"\n{Path(path).name}")
        if rec is None:
            print("  AI 생성 표시 없음")
        else:
            print(json.dumps(rec, ensure_ascii=False, indent=4))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("idphoto", description="AI 증명사진 파이프라인")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gate", help="업로드 사진 품질 게이팅")
    g.add_argument("photos", nargs="+")
    g.set_defaults(fn=cmd_gate)

    r = sub.add_parser("run", help="전체 파이프라인 실행")
    r.add_argument("photos", nargs="+")
    r.add_argument("--spec", default="id_kr", choices=sorted(SPECS))
    r.add_argument("--provider", default="mock", choices=["mock", "gemini"])
    r.add_argument("--model", default=None, help="프로바이더 모델 ID")
    r.add_argument("--n", type=int, default=12, help="생성 장수")
    r.add_argument("--present", type=int, default=5, help="노출 장수")
    r.add_argument("--retouch", type=float, default=0.5, help="보정 강도 0..1")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--wardrobe", default=None,
                   help="의상 프리셋 고정 (suit_black·suit_navy·shirt_white…)")
    r.add_argument("--backdrop", default=None, help="배경 프리셋 고정 (white·light_gray…)")
    r.add_argument("--out", default=None, help="저장 디렉터리")
    r.add_argument("--preview", action="store_true", help="가시 워터마크 적용")
    r.add_argument("--purpose", default="증명사진 생성",
                   help="ai_keys 원장에 남길 목적")
    r.add_argument("--est-usd", type=float, default=0.0,
                   help="예상 비용(USD). 파일럿으로 잰 값을 넣을 것 — 추측 금지")
    r.add_argument("--approval", default=None,
                   help="금액 기준 초과 시 CK 승인 id")
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("check", help="AI 생성 표시 확인")
    c.add_argument("photos", nargs="+")
    c.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
