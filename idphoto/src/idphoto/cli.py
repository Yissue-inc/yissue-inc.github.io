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


def _expand(patterns: list[str]) -> list[str]:
    """글롭 패턴을 파일 목록으로 편다.

    zsh 는 매치가 없으면 명령 자체를 실패시키므로(`no matches found`),
    사용자가 패턴을 따옴표로 감싸 넘기는 경우를 지원해야 한다. 셸이 이미
    펼친 경우에도 그대로 동작한다.
    """
    out: list[str] = []
    for pat in patterns:
        if any(c in pat for c in "*?["):
            out.extend(str(p) for p in sorted(Path().glob(pat)) if p.is_file())
        else:
            out.append(pat)
    return out


def _load(paths: list[str]):
    out = []
    for p in _expand(paths):
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


def cmd_overlay(args) -> int:
    """원본과 후보를 눈 위치로 정렬해 윤곽을 겹쳐 본다.

    품질 기준 §5 가 요구하는 사람 검사다. 자동 검사는 6~12% 수준의 미세한
    얼굴 깎기를 확실히 잡지 못하므로, 이 이미지를 보고 판단해야 한다.
    턱선에서 원본 윤곽(초록)이 후보 윤곽(빨강) 바깥에 있으면 깎인 것이다.
    """
    from .detect import FaceAnalyzer
    from .overlay import compare

    an = FaceAnalyzer()
    refs = _load(args.refs)
    if not refs:
        print("참조 사진을 읽지 못했습니다", file=sys.stderr)
        return 1
    ref_path, ref_img = refs[0]
    ref_faces = an.analyze(ref_img)
    if not ref_faces:
        print(f"참조 {Path(ref_path).name}: 얼굴 검출 실패", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for path, img in _load(args.photos):
        faces = an.analyze(img)
        if not faces:
            print(f"  {Path(path).name}: 얼굴 검출 실패 — 건너뜀", file=sys.stderr)
            continue
        strip = compare(ref_img, ref_faces[0], img, faces[0])
        dst = out / f"overlay_{Path(path).stem}.png"
        cv2.imwrite(str(dst), strip)
        print(f"  {dst}")
        n += 1

    print(f"\n{n}장 생성. 3번 패널의 턱선·볼 라인만 보세요 — "
          f"초록(원본)이 빨강(후보) 바깥이면 얼굴이 깎인 것입니다.")
    return 0


def cmd_calibrate(args) -> int:
    """사람 판정으로 임계값을 되맞춘다.

    catalog 가 낸 scores.csv 에 `human` 열을 채워서 넘기면(pass/fail),
    자동 판정과 어디서 갈리는지, 각 지표를 어디서 끊어야 사람 판단과
    가장 잘 맞는지를 알려준다.

    기준을 감으로 고치지 않기 위한 도구다 — 사람의 눈이 정답이고,
    임계값이 그걸 따라가야 한다.
    """
    import csv

    import numpy as np

    rows = []
    with open(args.scores, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            h = (r.get("human") or "").strip().lower()
            if h in ("pass", "1", "o", "y", "yes", "ok"):
                r["_human"] = True
            elif h in ("fail", "0", "x", "n", "no"):
                r["_human"] = False
            else:
                continue
            rows.append(r)

    if len(rows) < 4:
        print(f"라벨된 행이 {len(rows)}개뿐입니다. scores.csv 의 human 열에 "
              f"pass/fail 을 채워 주세요 (최소 4개, 양쪽 다 있어야 함).",
              file=sys.stderr)
        return 1

    human = np.array([r["_human"] for r in rows])
    auto = np.array([(r.get("verdict") or "") != "fail" for r in rows])
    agree = float((human == auto).mean())

    print(f"라벨 {len(rows)}개 (사람 통과 {int(human.sum())} / 탈락 {int((~human).sum())})")
    print(f"자동 판정과 일치율 {agree * 100:.0f}%\n")

    disagree = [(r, h, a) for r, h, a in zip(rows, human, auto) if h != a]
    if disagree:
        print("불일치 — 이 사진들이 기준을 고칠 근거입니다")
        for r, h, a in disagree:
            direction = "자동은 통과시켰는데 사람이 탈락" if a and not h \
                else "자동은 탈락시켰는데 사람이 통과"
            print(f"  {r.get('file', '?'):30s} cos {r.get('id_cos', '?'):>7s}  "
                  f"{direction}")
        print()

    # --- 지표별로 사람 판단을 가장 잘 가르는 임계값 ---
    metrics = [("id_cos", True), ("score", True), ("sharpness", True),
               ("chroma_shift", False), ("head_mm", None)]
    print(f"{'지표':14s} {'방향':>6s} {'최적 임계값':>11s} {'균형정확도':>10s}  현재 설정")
    from .config import DEFAULT
    current = {"id_cos": DEFAULT.qa.tau_id, "chroma_shift": DEFAULT.qa.max_skin_chroma_shift}

    for name, higher_is_pass in metrics:
        vals = []
        for r in rows:
            try:
                vals.append(float(r.get(name) or "nan"))
            except ValueError:
                vals.append(float("nan"))
        v = np.array(vals)
        ok = ~np.isnan(v)
        if ok.sum() < 4 or higher_is_pass is None:
            continue
        best, best_acc = None, 0.0
        for t in np.unique(v[ok]):
            pred = (v >= t) if higher_is_pass else (v <= t)
            tp = float((pred & human & ok).sum()); tn = float((~pred & ~human & ok).sum())
            p = float((human & ok).sum()); n = float((~human & ok).sum())
            if p == 0 or n == 0:
                continue
            acc = 0.5 * (tp / p + tn / n)
            if acc > best_acc:
                best, best_acc = float(t), acc
        if best is None:
            continue
        cur = current.get(name)
        cur_s = f"{cur}" if cur is not None else "-"
        arrow = "이상" if higher_is_pass else "이하"
        print(f"{name:14s} {arrow:>6s} {best:>11.3f} {best_acc * 100:>9.0f}%  {cur_s}")

    print("\n※ 균형정확도가 80% 미만인 지표는 사람 판단을 설명하지 못합니다 —")
    print("   그 축은 기준에서 빼거나, 사람이 실제로 보는 다른 것을 찾아야 합니다.")
    return 0


def cmd_catalog(args) -> int:
    """폴더 전체를 채점해 순위를 매기고 컨택트 시트를 만든다.

    후보가 수십 장일 때 한 장씩 보는 대신, 격자 한 장에 순위·유사도·판정을
    새겨 한눈에 고를 수 있게 한다. 상위 N장은 따로 크게 붙인다.
    """
    import csv

    import numpy as np

    from .config import DEFAULT
    from .detect import FaceAnalyzer
    from .framing import frame_to_spec
    from .identity import IdentityEncoder
    from .sheet import contact_sheet, strip
    from .specs import get_spec
    from . import qa

    an, enc = FaceAnalyzer(), IdentityEncoder()
    refs = _load(args.refs)
    embs, skins = [], []
    for path, img in refs:
        faces = an.analyze(img)
        if faces:
            embs.append(enc.embed(img, faces[0]))
            skins.append(qa._skin_lab(img, faces[0]))
    if not embs:
        print("참조 사진에서 얼굴을 찾지 못했습니다", file=sys.stderr)
        return 1
    reference = enc.reference(embs)
    ref_skin = tuple(float(np.median([s[i] for s in skins])) for i in range(3))
    spec = get_spec(args.spec)

    files = [f for f in _expand(args.photos) if Path(f).is_file()]
    if not files:
        print("채점할 사진이 없습니다", file=sys.stderr)
        return 1

    scored = []
    for path, img in _load(files):
        faces = an.analyze(img)
        if not faces:
            scored.append({"path": path, "image": img, "id_cos": 0.0,
                           "score": 0.0, "verdict": "fail",
                           "note": "no face", "cand": None})
            continue
        geo = faces[0]
        try:
            fr = frame_to_spec(img, geo, spec)
        except ValueError:
            fr = None
        c = qa.Candidate(variant_id=Path(path).name, image=img, face=geo,
                         embedding=enc.embed(img, geo), framing=fr)
        qa.evaluate(c, reference, ref_skin, DEFAULT.qa)
        if c.rejected:
            verdict, note = "fail", c.rejected.split(" (")[0]
        elif c.id_cos < DEFAULT.qa.tau_id_target:
            verdict, note = "near", f"below target {DEFAULT.qa.tau_id_target}"
        else:
            verdict, note = "pass", ""
        scored.append({"path": path, "image": img, "id_cos": c.id_cos,
                       "score": c.score, "verdict": verdict, "note": note,
                       "cand": c})

    scored.sort(key=lambda e: (e["verdict"] == "fail", -e["score"]))
    for i, e in enumerate(scored, 1):
        e["rank"] = i

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "contact_sheet.png"), contact_sheet(scored, cols=args.cols))
    top = scored[:args.top]
    cv2.imwrite(str(out / f"top{len(top)}.png"), strip(top))

    with open(out / "scores.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "file", "verdict", "human", "id_cos", "score",
                    "head_mm", "chroma_shift", "delta_L", "sharpness", "note"])
        for e in scored:
            c = e["cand"]
            w.writerow([e["rank"], Path(e["path"]).name, e["verdict"], "",
                        f"{e['id_cos']:.4f}", f"{e['score']:.4f}",
                        f"{c.framing.head_mm:.1f}" if c and c.framing else "",
                        f"{c.skin_chroma_shift:.1f}" if c else "",
                        f"{c.skin_delta_L:+.1f}" if c else "",
                        f"{c.quality:.3f}" if c else "", e["note"]])

    n_pass = sum(e["verdict"] == "pass" for e in scored)
    n_near = sum(e["verdict"] == "near" for e in scored)
    print(f"채점 {len(scored)}장 — 통과 {n_pass} · 목표미달 {n_near} · "
          f"탈락 {len(scored) - n_pass - n_near}")
    print(f"참조 {len(embs)}장 · 상호 최소 유사도 {enc.spread(embs):.3f}\n")
    print(f"{'순위':>4s} {'파일':26s} {'판정':>6s} {'유사도':>7s} {'종합':>7s} "
          f"{'머리mm':>7s} {'Δchroma':>8s}  비고")
    for e in scored[:args.top * 2]:
        c = e["cand"]
        head = f"{c.framing.head_mm:.1f}" if c and c.framing else "-"
        chroma = f"{c.skin_chroma_shift:.1f}" if c else "-"
        print(f"{e['rank']:>4d} {Path(e['path']).name[:26]:26s} {e['verdict']:>6s} "
              f"{e['id_cos']:>7.3f} {e['score']:>7.3f} {head:>7s} {chroma:>8s}  {e['note']}")

    print(f"\n기준선 — 인핸즈 0.646~0.674 / 게이트 {DEFAULT.qa.tau_id} "
          f"/ 목표 {DEFAULT.qa.tau_id_target}")
    print(f"\n저장: {out}/contact_sheet.png · {out}/top{len(top)}.png · {out}/scores.csv")
    print("→ contact_sheet.png 와 top 이미지를 Claude 에게 올리면 함께 고를 수 있습니다.")
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

    ov = sub.add_parser("overlay", help="원본과 정렬해 윤곽 겹쳐보기 (골격 검사)")
    ov.add_argument("photos", nargs="+", help="후보 이미지")
    ov.add_argument("--refs", nargs="+", required=True, help="참조(원본) 사진")
    ov.add_argument("--out", default="out/overlay")
    ov.set_defaults(fn=cmd_overlay)

    cal = sub.add_parser("calibrate", help="사람 판정으로 임계값 되맞추기")
    cal.add_argument("scores", help="human 열을 채운 scores.csv")
    cal.set_defaults(fn=cmd_calibrate)

    cat = sub.add_parser("catalog", help="폴더 전체 채점 + 컨택트 시트 생성")
    cat.add_argument("photos", nargs="+", help="후보 이미지 (글롭 가능)")
    cat.add_argument("--refs", nargs="+", required=True, help="참조(원본) 사진")
    cat.add_argument("--spec", default="id_kr", choices=sorted(SPECS))
    cat.add_argument("--top", type=int, default=12, help="크게 뽑을 상위 장수")
    cat.add_argument("--cols", type=int, default=6, help="시트 열 수")
    cat.add_argument("--out", default="out/catalog")
    cat.set_defaults(fn=cmd_catalog)

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
