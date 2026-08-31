"""단일 세션 데모 — 하드웨어 없이 90초 여정 전체를 콘솔에서 확인합니다.

    python -m mvp.demo
    python -m mvp.demo --realtime      # 로봇 동작에 실제 지연을 넣어 체감
    python -m mvp.demo --policy rule
"""
from __future__ import annotations

import argparse
import random
import tempfile
from pathlib import Path

from .catalog import Catalog
from .counselor import TemplateCounselor
from .recommender import Profile, Recommender
from .robot import MockArm
from .session import FeedbackInput, SessionRunner
from .skin import MockSkinAnalyzer
from .store import Store

BAR = "─" * 68


def render_metrics(m) -> str:
    lines = []
    for k, v in sorted(m.metrics.items(), key=lambda kv: -kv[1]):
        lines.append(f"    {k:<13} {'█' * int(v * 24):<24} {v:.2f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="bandit", choices=["bandit", "rule"])
    ap.add_argument("--persona", default="김서연")
    ap.add_argument("--realtime", action="store_true", help="로봇 동작 지연 시뮬레이션")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()

    db_path = args.db or str(Path(tempfile.mkdtemp()) / "kiosk.db")
    catalog = Catalog.load()
    store = Store(db_path)
    runner = SessionRunner(
        catalog=catalog,
        analyzer=MockSkinAnalyzer(seed=42),
        recommender=Recommender(catalog, policy=args.policy, seed=42),
        arm=_arm(args.realtime),
        store=store,
        counselor=TemplateCounselor(),
        seed=42,
    )
    profile = Profile(age_band="30s", budget_band="mid", skin_type="combination",
                      self_concerns=["pore", "pigmentation"])

    rng = random.Random(7)

    def feedback(rec, delivered):
        """실제로는 키오스크 터치 입력. 여기선 무작위 고객 반응."""
        if not delivered:
            return FeedbackInput()
        picked = rng.random() < 0.7
        return FeedbackInput(picked_up=picked,
                             applied=picked and rng.random() < 0.6,
                             rating=rng.choice([3, 4, 4, 5]) if picked else None,
                             purchased=picked and rng.random() < 0.25)

    print(f"\n{BAR}\n  AI 피지컬 뷰티 카운슬러 — 단일 세션 데모  (policy={args.policy})\n{BAR}")
    print("[00s] 대기 화면 · 사람 감지 → 인사")
    print("[10s] 개인정보/생체정보 별도 동의  ✔ 개인정보  ✔ 생체정보")
    print("[18s] 촬영 부스: 일반광 / 교차편광 / 평행편광 3컷")

    res = runner.run(profile=profile, persona=args.persona, feedback_fn=feedback)

    m = MockSkinAnalyzer(seed=42).analyze(hint=args.persona)
    print("[21s] 측정 결과")
    print(render_metrics(m))
    print(f"[30s] 문진: {profile.age_band} · {profile.skin_type} · 예산 {profile.budget_band}"
          f" · 직접 말한 고민 {profile.self_concerns}")

    s = res.script
    if s:
        print(f"[45s] 상담\n    🗣  {s.greeting}\n    🗣  {s.concerns_line}")
        if s.blocked_terms:
            print(f"    ⚠️  금지어 필터 작동: {s.blocked_terms}")

    for i, rec in enumerate(res.recommendations):
        state = "전달 완료" if res.delivered[i] else "❌ 파지 실패 → 직원 호출"
        tag = " [탐색]" if rec.is_exploration else ""
        print(f"[{55 + i * 15:02d}s] 로봇: 슬롯 {rec.product.slot_id:>2} → 슈트  "
              f"| {rec.product.label}{tag}  ({state})")
        print(f"       근거: {rec.reason}")
        print(f"       보상 r = {res.rewards[i] if res.rewards else 0.0}")

    if s:
        print(f"[80s] 🗣  {s.usage_tip}")

    ok, n = store.robot_success_rate()
    acc, total = store.acceptance_rate()
    print(f"\n{BAR}")
    print(f"  세션 ID          : {res.session_id}   (exit={res.exit_stage})")
    print(f"  로봇 성공률      : {ok}/{n}")
    print(f"  추천 수락률      : {acc}/{total}")
    print(f"  정책 버전        : {runner.recommender.version}")
    print(f"  로그 DB          : {db_path}")
    print(f"{BAR}\n")
    store.close()


def _arm(realtime: bool) -> MockArm:
    arm = MockArm(cycle_s=12.0 if realtime else 0.0, failure_rate=0.03,
                  seed=1, realtime=realtime)
    arm.connect()
    arm.home()
    return arm


if __name__ == "__main__":
    main()
