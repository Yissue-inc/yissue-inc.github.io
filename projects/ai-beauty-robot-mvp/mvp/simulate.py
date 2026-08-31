"""학습 루프 시뮬레이션 — "정말 똑똑해지는가"를 하드웨어 없이 검증합니다.

동일한 고객 스트림을 룰 기반(S0)과 컨텍스추얼 밴딧(S1)에 각각 통과시켜
수락률(제품을 실제로 집어간 비율)이 세션이 쌓일수록 벌어지는지 봅니다.

    python -m mvp.simulate --sessions 800

숨겨진 '진짜' 고객 선호에는 룰이 모르는 요인 4개를 심어두었습니다.
밴딧이 이걸 찾아내는지가 관전 포인트입니다:
  1. 젊은 층은 선케어/트러블 카테고리를 훨씬 잘 받는다
  2. 각질 제품은 즉석에서 잘 안 집는다   ← 룰은 texture 지표만 보고 계속 추천함
  3. 진정/수분은 누구에게나 안전한 선택
  4. 저예산 고객에게 고가 제품은 강한 거부
"""
from __future__ import annotations

import argparse
import random
import tempfile
from pathlib import Path

from .catalog import Catalog
from .recommender import CLUSTER_CONCERNS, Profile, Recommender
from .robot import MockArm
from .session import FeedbackInput, SessionRunner
from .skin import METRICS, Measurement
from .store import Store

AGE_BANDS = ["10s", "20s", "30s", "40s", "50s+"]
BUDGETS = ["low", "mid", "high"]
SKIN_TYPES = ["dry", "oily", "combination", "sensitive", "normal"]


def clamp(v: float, lo: float = 0.02, hi: float = 0.95) -> float:
    return max(lo, min(hi, v))


def make_customers(n: int, seed: int = 0):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        metrics = {k: round(clamp(rng.betavariate(2, 3), 0.0, 1.0), 3) for k in METRICS}
        m = Measurement(metrics=metrics, quality=round(rng.uniform(0.75, 1.0), 3),
                        analyzer="sim")
        p = Profile(age_band=rng.choice(AGE_BANDS), budget_band=rng.choice(BUDGETS),
                    skin_type=rng.choice(SKIN_TYPES),
                    self_concerns=rng.sample(METRICS, k=rng.randint(0, 2)))
        out.append((m, p))
    return out


def true_affinity(cluster: str, m: Measurement, profile: Profile, product) -> float:
    """시뮬레이터만 아는 '진짜' 선호. 추천 엔진은 이 함수를 절대 못 봅니다."""
    concerns = CLUSTER_CONCERNS.get(cluster, [])
    hits = [m.metrics.get(c, 0.0) for c in concerns if c in m.metrics]
    base = sum(hits) / len(hits) if hits else 0.30
    a = 0.22 + 0.55 * base
    if profile.age_band in ("10s", "20s") and cluster in ("C6", "C7"):
        a += 0.25
    if cluster == "C5":
        a -= 0.25
    if cluster == "C1":
        a += 0.12
    if profile.budget_band == "low" and product.price_band == "high":
        a -= 0.30
    if profile.budget_band == "high" and product.price_band == "low":
        a -= 0.08
    return clamp(a)


class SimulatedCustomer:
    def __init__(self, m, p, rng):
        self.m, self.p, self.rng = m, p, rng
        self.accepted = 0
        self.shown = 0

    def __call__(self, rec, delivered):
        if not delivered:
            return FeedbackInput()
        a = true_affinity(rec.cluster, self.m, self.p, rec.product)
        picked = self.rng.random() < a
        self.shown += 1
        self.accepted += int(picked)
        return FeedbackInput(
            picked_up=picked,
            applied=picked and self.rng.random() < 0.65,
            rating=max(1, min(5, round(1 + 4 * a + self.rng.gauss(0, 0.5)))) if picked else None,
            purchased=picked and self.rng.random() < 0.30 * a,
        )


def run_policy(policy: str, customers, seed: int, window: int):
    catalog = Catalog.load()
    db = str(Path(tempfile.mkdtemp()) / f"{policy}.db")
    store = Store(db)
    arm = MockArm(failure_rate=0.02, seed=seed)
    arm.connect()
    runner = SessionRunner(catalog=catalog, analyzer=None,
                           recommender=Recommender(catalog, policy=policy, seed=seed,
                                                   version=f"{policy}-sim"),
                           arm=arm, store=store, seed=seed)
    rng = random.Random(seed + 999)
    shown = accepted = 0
    curve, cluster_hits = [], {}
    for i, (m, p) in enumerate(customers, start=1):
        cust = SimulatedCustomer(m, p, rng)
        # analyzer 를 우회하고 시뮬레이션 측정값을 직접 주입
        runner.analyzer = _Fixed(m)
        res = runner.run(profile=p, persona=None, feedback_fn=cust)
        for rec in res.recommendations:
            cluster_hits[rec.cluster] = cluster_hits.get(rec.cluster, 0) + 1
        shown += cust.shown
        accepted += cust.accepted
        if i % window == 0:
            curve.append((i, accepted / shown if shown else 0.0))
            shown = accepted = 0
    store.close()
    return curve, cluster_hits, runner.recommender


class _Fixed:
    def __init__(self, m): self.m = m
    def analyze(self, frames=None, *, hint=None): return self.m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=800)
    ap.add_argument("--window", type=int, default=100)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    customers = make_customers(args.sessions, seed=args.seed)
    rule_curve, rule_hits, _ = run_policy("rule", customers, args.seed, args.window)
    band_curve, band_hits, rec = run_policy("bandit", customers, args.seed, args.window)

    print(f"\n{'=' * 66}")
    print(f"  학습 루프 시뮬레이션 — 세션 {args.sessions}건, 동일 고객 스트림")
    print(f"{'=' * 66}")
    print(f"\n  {'구간':>12} {'룰 기반(S0)':>14} {'밴딧(S1)':>12} {'차이':>10}")
    print(f"  {'-' * 52}")
    for (i, r), (_, b) in zip(rule_curve, band_curve):
        delta = (b - r) * 100
        bar = "▲" * max(0, int(delta / 1.5))
        print(f"  {i - args.window + 1:>5}-{i:<6} {r:>12.1%} {b:>12.1%} {delta:>+8.1f}p {bar}")

    r_all = sum(r for _, r in rule_curve) / len(rule_curve)
    b_all = sum(b for _, b in band_curve) / len(band_curve)
    r_last = rule_curve[-1][1]
    b_last = band_curve[-1][1]
    print(f"  {'-' * 52}")
    print(f"  {'전체 평균':>12} {r_all:>12.1%} {b_all:>12.1%} {(b_all - r_all) * 100:>+8.1f}p")
    print(f"  {'마지막 구간':>11} {r_last:>12.1%} {b_last:>12.1%} {(b_last - r_last) * 100:>+8.1f}p")

    print("\n  클러스터별 추천 횟수 (밴딧이 무엇을 버리고 무엇을 늘렸는가)")
    print(f"  {'클러스터':<10}{'이름':<12}{'룰':>8}{'밴딧':>8}{'변화':>10}")
    cat = Catalog.load()
    for c in cat.cluster_ids:
        r, b = rule_hits.get(c, 0), band_hits.get(c, 0)
        arrow = "↑" if b > r * 1.15 else ("↓" if b < r * 0.85 else "·")
        print(f"  {c:<10}{cat.clusters.get(c, ''):<12}{r:>8}{b:>8}{b - r:>9}{arrow}")

    print("\n  밴딧이 각 클러스터에서 관측한 세션 수 n:")
    print("   ", {k: v for k, v in sorted(rec.bandit.n.items())})
    print("\n  ※ 심어둔 정답: C5(각질)는 즉석 수락률이 낮고, C1(진정/수분)은 높습니다.")
    print("     밴딧이 C5 추천을 줄이고 C1 을 늘렸다면 학습 루프가 동작하는 것입니다.\n")


if __name__ == "__main__":
    main()
