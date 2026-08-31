"""추천 엔진 — 룰 기반(S0) → 컨텍스추얼 밴딧 LinUCB(S1).

핵심 설계:
  * 밴딧의 arm 은 개별 SKU 가 아니라 **제품 클러스터(8~30개)** 입니다.
    SKU 단위로 하면 매장 데이터 속도로는 영원히 학습이 안 됩니다.
  * 콜드스타트는 룰 기반 점수를 prior 로 섞어서 해결합니다.
    가중치 w = prior_strength / (prior_strength + n_arm) 로 자연 감쇠.
  * top-k 중 한 자리는 **항상 탐색 슬롯**(is_exploration=True). 노출 편향 방지.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .catalog import Catalog, Product
from .linalg import dot, identity, inverse, matvec, outer_add, zeros
from .skin import METRICS, Measurement

# 컨텍스트 벡터: [bias] + 피부지표 10 + [연령대, 예산대] = 13 차원
CONTEXT_DIM = 1 + len(METRICS) + 2

AGE_BANDS = ["10s", "20s", "30s", "40s", "50s+"]
BUDGET_BANDS = ["low", "mid", "high"]

# 클러스터가 겨냥하는 고민 (products.json 의 clusters 와 대응)
CLUSTER_CONCERNS: dict[str, list[str]] = {
    "C1": ["dryness", "redness"],
    "C2": ["oiliness", "pore"],
    "C3": ["pigmentation", "tone"],
    "C4": ["wrinkle"],
    "C5": ["texture"],
    "C6": ["protection"],
    "C7": ["acne"],
    "C8": ["dark_circle"],
}


@dataclass
class Profile:
    age_band: str = "30s"
    budget_band: str = "mid"
    skin_type: str = "normal"
    self_concerns: list[str] = field(default_factory=list)

    def as_features(self) -> list[float]:
        age = AGE_BANDS.index(self.age_band) / (len(AGE_BANDS) - 1) if self.age_band in AGE_BANDS else 0.5
        bud = BUDGET_BANDS.index(self.budget_band) / (len(BUDGET_BANDS) - 1) if self.budget_band in BUDGET_BANDS else 0.5
        return [age, bud]


def build_context(m: Measurement, profile: Profile) -> list[float]:
    """측정값 + 프로필 → 컨텍스트 벡터. 순서가 곧 스키마입니다. 절대 바꾸지 마세요."""
    return [1.0] + [float(m.metrics.get(k, 0.0)) for k in METRICS] + profile.as_features()


# ---------------------------------------------------------------- 룰 기반 (S0)

def rule_cluster_score(cluster: str, m: Measurement, profile: Profile) -> float:
    """MD/전문가가 작성하는 규칙표. 0~1. 실제 운영 시 rules.yaml 로 빼세요."""
    concerns = CLUSTER_CONCERNS.get(cluster, [])
    hit = [m.metrics.get(c, 0.0) for c in concerns if c in m.metrics]
    score = sum(hit) / len(hit) if hit else 0.0
    # 자외선차단은 지표에 없으므로 항상 기본 수요가 있다고 본다
    if cluster == "C6":
        score = max(score, 0.35)
    # 고객이 직접 말한 고민에 가중
    if any(c in profile.self_concerns for c in concerns):
        score = min(1.0, score + 0.25)
    # 연령대 보정 (주름/탄력은 나이와 함께)
    if cluster == "C4" and profile.age_band in ("40s", "50s+"):
        score = min(1.0, score + 0.15)
    if cluster == "C7" and profile.age_band in ("10s", "20s"):
        score = min(1.0, score + 0.10)
    return round(score, 4)


def pick_product_in_cluster(cat: Catalog, cluster: str, profile: Profile) -> Product | None:
    """클러스터가 정해진 뒤 SKU 를 고르는 건 단순 규칙으로 충분합니다."""
    cands = cat.by_cluster(cluster)
    if not cands:
        return None

    def key(p: Product) -> tuple:
        budget_fit = 0 if p.price_band == profile.budget_band else 1
        type_fit = 0 if profile.skin_type in p.skin_types else 1
        return (budget_fit, type_fit, -p.stock, p.price)

    return sorted(cands, key=key)[0]


# ------------------------------------------------------------- LinUCB (S1)

class LinUCB:
    """Disjoint LinUCB. arm 마다 독립적인 능선회귀 + 신뢰상한."""

    def __init__(self, arms: list[str], dim: int = CONTEXT_DIM, alpha: float = 0.6,
                 prior_strength: float = 12.0, seed: int | None = None):
        self.arms = list(arms)
        self.dim = dim
        self.alpha = alpha
        self.prior_strength = prior_strength
        self.A = {a: identity(dim) for a in self.arms}
        self.b = {a: zeros(dim) for a in self.arms}
        self.n = {a: 0 for a in self.arms}
        self.rng = random.Random(seed)

    # --- 점수
    def _ucb(self, arm: str, x: list[float]) -> tuple[float, float]:
        Ainv = inverse(self.A[arm])
        theta = matvec(Ainv, self.b[arm])
        mean = dot(theta, x)
        var = max(0.0, dot(x, matvec(Ainv, x)))
        return mean, self.alpha * math.sqrt(var)

    def score(self, arm: str, x: list[float], prior: float) -> float:
        mean, bonus = self._ucb(arm, x)
        w = self.prior_strength / (self.prior_strength + self.n[arm])
        return (1 - w) * (mean + bonus) + w * prior

    def update(self, arm: str, x: list[float], reward: float) -> None:
        outer_add(self.A[arm], x)
        self.b[arm] = [bi + reward * xi for bi, xi in zip(self.b[arm], x)]
        self.n[arm] += 1

    # --- 직렬화 (정책 버전 배포용)
    def state_dict(self) -> dict:
        return {"arms": self.arms, "dim": self.dim, "alpha": self.alpha,
                "prior_strength": self.prior_strength,
                "A": self.A, "b": self.b, "n": self.n}

    def load_state_dict(self, s: dict) -> None:
        self.arms, self.dim = s["arms"], s["dim"]
        self.alpha, self.prior_strength = s["alpha"], s["prior_strength"]
        self.A = {k: [list(r) for r in v] for k, v in s["A"].items()}
        self.b = {k: list(v) for k, v in s["b"].items()}
        self.n = dict(s["n"])


# ------------------------------------------------------------- 추천 파사드

@dataclass
class Recommendation:
    product: Product
    cluster: str
    rank: int
    score: float
    is_exploration: bool
    reason: str


class Recommender:
    """policy='rule' 이면 S0, policy='bandit' 이면 S1.

    A/B 비교를 위해 두 정책을 같은 인터페이스로 노출합니다.
    """

    def __init__(self, catalog: Catalog, policy: str = "bandit", epsilon: float = 0.10,
                 seed: int | None = None, version: str | None = None):
        self.catalog = catalog
        self.policy = policy
        self.epsilon = epsilon
        self.rng = random.Random(seed)
        self.bandit = LinUCB(catalog.cluster_ids, seed=seed)
        self.version = version or f"{policy}-v1"

    def recommend(self, m: Measurement, profile: Profile, k: int = 2) -> list[Recommendation]:
        x = build_context(m, profile)
        priors = {c: rule_cluster_score(c, m, profile) for c in self.catalog.cluster_ids}

        if self.policy == "rule":
            scored = sorted(priors.items(), key=lambda kv: -kv[1])
        else:
            scored = sorted(
                ((c, self.bandit.score(c, x, priors[c])) for c in self.catalog.cluster_ids),
                key=lambda kv: -kv[1],
            )

        chosen: list[tuple[str, float, bool]] = [(c, s, False) for c, s in scored[:k]]

        # 탐색 슬롯: 마지막 한 자리를 확률 epsilon 으로 무작위 클러스터로 교체
        if k >= 2 and self.rng.random() < self.epsilon:
            pool = [c for c in self.catalog.cluster_ids if c not in {c for c, _, _ in chosen}]
            if pool:
                c = self.rng.choice(pool)
                chosen[-1] = (c, priors[c], True)

        out: list[Recommendation] = []
        for rank, (cluster, score, explore) in enumerate(chosen, start=1):
            p = pick_product_in_cluster(self.catalog, cluster, profile)
            if p is None:
                continue
            out.append(Recommendation(
                product=p, cluster=cluster, rank=rank, score=round(score, 4),
                is_exploration=explore,
                reason=self._reason(cluster, m),
            ))
        return out

    def _reason(self, cluster: str, m: Measurement) -> str:
        """'왜 이 제품인가' 한 줄 근거. 투명성이 신뢰를 만듭니다.

        ⚠️ 진단·치료·효능 단정 표현 금지 (의료기기법/화장품법). 측정값 서술에 머무를 것.
        """
        labels = {"dryness": "건조", "redness": "붉은기", "oiliness": "유분",
                  "pore": "모공", "texture": "결", "wrinkle": "잔주름",
                  "pigmentation": "색소 침착", "dark_circle": "눈가 어두움",
                  "acne": "트러블", "tone": "톤 균일도", "protection": "자외선 노출"}
        cs = CLUSTER_CONCERNS.get(cluster, [])
        named = [labels.get(c, c) for c in cs if m.metrics.get(c, 0) > 0.3] or [labels.get(c, c) for c in cs]
        return f"측정값에서 {'·'.join(named[:2])} 항목이 상대적으로 높게 나와 이 카테고리를 함께 보시길 제안드려요."

    # 학습 반영
    def learn(self, m: Measurement, profile: Profile, cluster: str, reward: float) -> None:
        if self.policy != "bandit":
            return
        if m.quality < 0.6:   # 저품질 촬영은 학습에서 제외
            return
        self.bandit.update(cluster, build_context(m, profile), reward)
