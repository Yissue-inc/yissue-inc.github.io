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

    models = [m.strip() for m in args.models.split(",")] if args.models else None
    pipe = Pipeline(provider=args.provider, model=args.model, models=models)
    try:
        res = pipe.run([img for _, img in loaded], spec_key=args.spec,
                       n_generate=args.n, n_present=args.present,
                       retouch=args.retouch, seed=args.seed, presets=presets,
                       variants=[x.strip() for x in args.variants.split(",")]
                       if args.variants else None)
    except ValueError as exc:
        print(f"중단: {exc}", file=sys.stderr)
        return 1

    summary = res.summary()
    if res.usage:
        summary["usage"] = res.usage
        summary["est_usd_next_run"] = round(
            res.cost_usd / max(1, summary["generated"]) * args.n, 4)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for label, key in (("모델별", "by_model"), ("프롬프트 변형별", "by_variant")):
        groups = summary.get(key, {})
        if len(groups) <= 1:
            continue
        print(f"\n{label} 비교")
        print(f"  {'':30s} {'생성':>4s} {'통과':>4s} {'통과율':>7s} {'유사도평균':>10s} {'최고':>7s}")
        for name, m in sorted(groups.items(), key=lambda kv: -kv[1]["id_cos_mean"]):
            print(f"  {name:30s} {m['n']:>4d} {m['passed']:>4d} "
                  f"{m['pass_rate']:>7.2f} {m['id_cos_mean']:>10.3f} {m['id_cos_max']:>7.3f}")

    print("\n선발 결과")
    for rank, c in enumerate(res.selected, 1):
        fr = c.framing
        print(f"  {rank}. {c.variant_id}  점수 {c.score:.3f}  유사도 {c.id_cos:.3f}  "
              f"머리 {fr.head_mm:.1f}mm  {c.preset['wardrobe']}/{c.preset['backdrop']}"
              + (f"  [{c.model}/{c.variant}]" if c.model else ""))

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


def cmd_prompt(args) -> int:
    """프롬프트를 그대로 출력한다.

    웹 UI(Gemini·ChatGPT 등)에 붙여넣어 손으로 생성해 볼 때 쓴다. API 없이
    프롬프트 효과를 확인하는 가장 빠른 경로다 — 결과 이미지를 되가져오면
    파이프라인이 유사도·규격·피부톤을 그대로 측정한다.
    """
    from . import prompts

    preset = prompts.Preset("cli", args.wardrobe, args.backdrop, args.lighting)
    for variant in ([args.variant] if args.variant else list(prompts.VARIANTS)):
        print(f"\n{'=' * 64}\n[{variant}]  {args.wardrobe} / {args.backdrop}\n{'=' * 64}")
        print(prompts.build(preset, variant))
    return 0


def cmd_measure(args) -> int:
    """손으로 만든 결과물을 파이프라인 지표로 채점한다.

    웹 UI 로 생성한 이미지든 다른 서비스 출력이든, 참조 사진만 있으면
    유사도·규격·피부톤을 같은 기준으로 잰다. API 없이 프롬프트 효과를
    비교하는 경로다.
    """
    import numpy as np

    from .config import DEFAULT
    from .detect import FaceAnalyzer
    from .framing import frame_to_spec
    from .identity import IdentityEncoder
    from .specs import get_spec
    from . import qa

    an, enc = FaceAnalyzer(), IdentityEncoder()
    refs = _load(args.refs)
    if not refs:
        print("참조 사진을 읽지 못했습니다", file=sys.stderr)
        return 1

    embs, skins = [], []
    for path, img in refs:
        faces = an.analyze(img)
        if not faces:
            print(f"  참조 {Path(path).name}: 얼굴 검출 실패 — 건너뜀", file=sys.stderr)
            continue
        embs.append(enc.embed(img, faces[0]))
        skins.append(qa._skin_lab(img, faces[0]))
    if not embs:
        print("참조 사진에서 얼굴을 찾지 못했습니다", file=sys.stderr)
        return 1

    reference = enc.reference(embs)
    ref_skin = tuple(float(np.median([s[i] for s in skins])) for i in range(3))
    spec = get_spec(args.spec)
    print(f"참조 {len(embs)}장 · 상호 최소 유사도 {enc.spread(embs):.3f}")
    print(f"{'파일':24s} {'유사도':>7s} {'머리mm':>7s} {'Δchroma':>8s} {'ΔL*':>7s} "
          f"{'선명도':>7s} {'점수':>7s}  판정")

    for path, img in _load(args.photos):
        faces = an.analyze(img)
        if not faces:
            print(f"{Path(path).name:24s} {'얼굴 검출 실패':>40s}")
            continue
        geo = faces[0]
        try:
            fr = frame_to_spec(img, geo, spec)
        except ValueError:
            fr = None
        c = qa.Candidate(variant_id=Path(path).name, image=img, face=geo,
                         embedding=enc.embed(img, geo), framing=fr)
        qa.evaluate(c, reference, ref_skin, DEFAULT.qa)
        verdict = "통과" if c.rejected is None else c.rejected
        head = f"{fr.head_mm:.1f}" if fr else "-"
        print(f"{Path(path).name:24s} {c.id_cos:>7.3f} {head:>7s} "
              f"{c.skin_chroma_shift:>8.1f} {c.skin_delta_L:>+7.1f} "
              f"{c.quality:>7.3f} {c.score:>7.3f}  {verdict}")

    print(f"\n기준선 — 인핸즈 출력 유사도 0.646~0.674 / 게이트 {DEFAULT.qa.tau_id} "
          f"/ 목표 {DEFAULT.qa.tau_id_target}")
    return 0


def cmd_doctor(args) -> int:
    """실행 준비 상태 점검. 생성 호출 전에 막힐 곳을 미리 찾는다."""
    import requests

    from .generate.models import MODELS
    ok = True

    print("모델 파일")
    from .detect import MODELS_DIR
    for f in ("yunet_2023mar.onnx", "sface_2021dec.onnx", "face_landmarker.task"):
        p = MODELS_DIR / f
        mark = "✓" if p.exists() else "✗"
        ok &= p.exists()
        size = f"{p.stat().st_size/1e6:.1f}MB" if p.exists() else "없음 — fetch_models.sh"
        print(f"  {mark} {f:28s} {size}")

    print("\n의존성")
    for m in ("cv2", "numpy", "PIL", "piexif"):
        try:
            __import__(m); print(f"  ✓ {m}")
        except ImportError:
            print(f"  ✗ {m} — pip install -r requirements.txt"); ok = False
    try:
        from .detect import FaceAnalyzer
        print(f"  {'✓' if FaceAnalyzer().landmarker_available else '!'} mediapipe "
              f"{'(478점 랜드마크 사용 가능)' if FaceAnalyzer().landmarker_available else '(폴백 모드)'}")
    except Exception as exc:
        print(f"  ! mediapipe — {str(exc)[:60]}")

    print("\n생성 API 인증")
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         timeout=30)
        if r.status_code == 200:
            ids = {m["name"].split("/")[-1] for m in r.json().get("models", [])}
            print("  ✓ 인증됨")
            for name in MODELS:
                if MODELS[name].deprecated:
                    continue
                print(f"    {'✓' if name in ids else '?'} {name}")
        elif r.status_code in (401, 403):
            ok = False
            print(f"  ✗ HTTP {r.status_code} — 인증 정보가 붙지 않았습니다.")
            print("    클라우드 환경 API credential 확인:")
            print("      Allowed websites : generativelanguage.googleapis.com")
            print("      Custom header    : x-goog-api-key  (Prefix 비움)")
            print("      목록에 'Not sent' 표시가 있으면 그 아래 사유를 보세요.")
            print("    또는 GEMINI_API_KEY 환경변수 + 새 세션.")
        else:
            ok = False
            print(f"  ✗ HTTP {r.status_code}: {r.text[:120]}")
    except Exception as exc:
        ok = False
        print(f"  ✗ 연결 실패: {str(exc)[:100]}")

    print(f"\n{'준비 완료' if ok else '위 ✗ 항목을 해결해야 실행할 수 있습니다'}")
    return 0 if ok else 1


def _silence_mediapipe_teardown() -> None:
    """MediaPipe 가 인터프리터 종료 중에 뱉는 트레이스백만 숨긴다.

    MediaPipe 의 FaceLandmarker.__del__ 은 종료 중에 이미 내려간 내부 실행기를
    건드리다 실패한다. 두 가지 형태로 나온다:
      RuntimeError: cannot schedule new futures after shutdown
      TypeError: 'NoneType' object is not callable   (모듈 전역이 해제된 뒤)
    둘 다 무해하지만 모든 실행 끝에 트레이스백이 찍혀 진짜 오류처럼 보인다.
    특히 파일럿 결과를 붙여넣어 공유할 때 혼란을 준다.

    라이브러리를 건드리는 대신 CLI 경계에서 **mediapipe 의 finalizer 에서 난
    것만** 거른다. 다른 unraisable 예외는 그대로 보고한다.

    __del__ 에서 난 예외의 unraisable.object 는 인스턴스가 아니라 그 __del__
    함수 객체다 — 그래서 함수의 __module__/__qualname__ 으로 판정한다.
    """
    prev = sys.unraisablehook

    def hook(unraisable):
        try:
            obj = unraisable.object
            where = (f"{getattr(obj, '__module__', '')}."
                     f"{getattr(obj, '__qualname__', '')}")
            if "mediapipe" in where.lower():
                return
        except Exception:
            return
        if prev is not None:
            prev(unraisable)

    sys.unraisablehook = hook


def main(argv: list[str] | None = None) -> int:
    _silence_mediapipe_teardown()
    ap = argparse.ArgumentParser("idphoto", description="AI 증명사진 파이프라인")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gate", help="업로드 사진 품질 게이팅")
    g.add_argument("photos", nargs="+")
    g.set_defaults(fn=cmd_gate)

    r = sub.add_parser("run", help="전체 파이프라인 실행")
    r.add_argument("photos", nargs="+")
    r.add_argument("--spec", default="id_kr", choices=sorted(SPECS))
    r.add_argument("--provider", default="mock", choices=["mock", "gemini"])
    r.add_argument("--model", default=None, help="프로바이더 모델 ID (단일)")
    r.add_argument("--models", default=None,
                   help="쉼표 구분 모델 목록 — 생성을 라운드로빈으로 나눠 비교한다")
    r.add_argument("--variants", default=None,
                   help="쉼표 구분 프롬프트 변형 (baseline·lock·measured)")
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

    ms = sub.add_parser("measure", help="손으로 만든 결과물을 지표로 채점")
    ms.add_argument("photos", nargs="+", help="채점할 결과 이미지")
    ms.add_argument("--refs", nargs="+", required=True, help="참조(원본) 사진")
    ms.add_argument("--spec", default="id_kr", choices=sorted(SPECS))
    ms.set_defaults(fn=cmd_measure)

    pr = sub.add_parser("prompt", help="프롬프트 출력 (웹 UI 에 붙여넣기용)")
    pr.add_argument("--variant", default=None, help="baseline·lock·measured (생략 시 전부)")
    pr.add_argument("--wardrobe", default="suit_navy")
    pr.add_argument("--backdrop", default="white")
    pr.add_argument("--lighting", default="studio_3pt")
    pr.set_defaults(fn=cmd_prompt)

    d = sub.add_parser("doctor", help="실행 준비 상태 점검")
    d.set_defaults(fn=cmd_doctor)

    c = sub.add_parser("check", help="AI 생성 표시 확인")
    c.add_argument("photos", nargs="+")
    c.set_defaults(fn=cmd_check)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
