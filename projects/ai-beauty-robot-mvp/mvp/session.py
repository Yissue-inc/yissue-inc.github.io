"""세션 상태머신 — 대기 → 동의 → 촬영 → 문진 → 추천 → 로봇전달 → 피드백 → 학습.

PLAN.md 2장의 90초 여정과 1:1로 대응합니다.
모든 단계는 반드시 로그를 남깁니다. 로그 없는 단계는 존재하지 않는 단계입니다.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .catalog import Catalog
from .counselor import Counselor, TemplateCounselor
from .recommender import Profile, Recommender, build_context
from .robot import RobotArm, RobotError
from .skin import SkinAnalyzer

# 보상 가중치 — PLAN.md 6.2. 측정 가능한 것만 0 이 아닌 값을 줍니다.
REWARD_WEIGHTS = {
    "picked_up": 0.30,   # 슈트에서 실제로 집어감
    "applied":   0.30,   # 테스터 사용
    "rating":    0.20,   # 1~5 별점 → 0~1 정규화 후 곱
    "purchased": 1.00,   # POS 연동 또는 직원 태블릿 입력
}
EXIT_PENALTY = 0.20


@dataclass
class FeedbackInput:
    """키오스크 UI 가 세션 말미에 채워 넣는 값 (제품별)."""
    picked_up: bool = False
    applied: bool = False
    rating: int | None = None      # 1~5
    purchased: bool = False


@dataclass
class SessionResult:
    session_id: str
    recommendations: list = field(default_factory=list)
    rec_ids: list[str] = field(default_factory=list)
    rewards: list[float] = field(default_factory=list)
    delivered: list[bool] = field(default_factory=list)
    exit_stage: str = "completed"
    script: object | None = None


class SessionRunner:
    def __init__(self, *, catalog: Catalog, analyzer: SkinAnalyzer, recommender: Recommender,
                 arm: RobotArm, store, counselor: Counselor | None = None,
                 store_id: str = "STORE-01", device_id: str = "KIOSK-01",
                 seed: int | None = None):
        self.catalog = catalog
        self.analyzer = analyzer
        self.recommender = recommender
        self.arm = arm
        self.store = store
        self.counselor = counselor or TemplateCounselor()
        self.store_id, self.device_id = store_id, device_id
        self.rng = random.Random(seed)

    # ------------------------------------------------------------------ run
    def run(self, *, profile: Profile, persona: str | None = None,
            consent_personal: bool = True, consent_biometric: bool = True,
            feedback_fn=None, k: int = 2, staff_intervened: bool = False) -> SessionResult:

        sid = self.store.start_session(
            store_id=self.store_id, device_id=self.device_id,
            consent_personal=consent_personal, consent_biometric=consent_biometric,
            policy_version=self.recommender.version)
        res = SessionResult(session_id=sid)

        # 1) 동의 게이트 — 생체정보 미동의면 촬영 없이 문진만으로 진행 (서비스 자체는 계속)
        if not consent_personal:
            self.store.end_session(sid, "consent_declined", staff_intervened)
            res.exit_stage = "consent_declined"
            return res

        # 2) 촬영 + 측정
        if consent_biometric:
            m = self.analyzer.analyze(hint=persona)
        else:
            from .skin import METRICS, Measurement
            m = Measurement(metrics={k2: 0.35 for k2 in METRICS}, quality=0.0,
                            analyzer="survey_only")
        self.store.log_measurement(sid, m)
        self.store.log_survey(sid, profile)

        # 3) 추천
        recs = self.recommender.recommend(m, profile, k=k)
        if not recs:
            self.store.end_session(sid, "no_recommendation", staff_intervened)
            res.exit_stage = "no_recommendation"
            return res

        # 4) 상담 멘트 (LLM 스트리밍 ↔ 로봇 동작 병렬화 지점)
        res.script = self.counselor.script(m, profile, recs)

        # 5) 전달 순서 랜덤화 — 전달 순서 편향 방지 (PLAN.md 6.3)
        order = list(range(len(recs)))
        self.rng.shuffle(order)

        features = build_context(m, profile)
        rec_ids: list[str] = [""] * len(recs)
        for deliver_idx, i in enumerate(order, start=1):
            rec_ids[i] = self.store.log_recommendation(
                sid, recs[i], features, self.recommender.version, deliver_idx)

        # 6) 로봇 전달
        delivered = [False] * len(recs)
        for i in order:
            rec = recs[i]
            try:
                result = self.arm.pick_and_deliver(rec.product.slot_id, rec.product.grip_force)
            except RobotError:
                self.store.end_session(sid, "robot_unavailable", staff_intervened)
                res.exit_stage = "robot_unavailable"
                res.recommendations, res.rec_ids = recs, rec_ids
                return res
            self.store.log_robot(sid, rec.product.id, result)
            delivered[i] = result.ok
            if not result.ok:
                self.store.log_feedback(sid, rec_ids[i], "skipped", 1.0)

        # 7) 피드백 수집 (실제로는 키오스크 터치 입력)
        rewards: list[float] = []
        for i, rec in enumerate(recs):
            fb = feedback_fn(rec, delivered[i]) if feedback_fn else FeedbackInput()
            r = self._log_and_score(sid, rec_ids[i], fb, delivered[i])
            rewards.append(r)
            # 8) 학습 — 저품질 촬영/직원 개입 세션은 recommender.learn 내부에서 걸러집니다
            if not staff_intervened:
                self.recommender.learn(m, profile, rec.cluster, r)

        self.store.end_session(sid, "completed", staff_intervened)
        res.recommendations, res.rec_ids, res.rewards, res.delivered = recs, rec_ids, rewards, delivered
        return res

    # --------------------------------------------------------------- reward
    def _log_and_score(self, sid: str, rec_id: str, fb: FeedbackInput, delivered: bool) -> float:
        if not delivered:
            return 0.0
        r = 0.0
        if fb.picked_up:
            self.store.log_feedback(sid, rec_id, "picked_up", 1.0)
            r += REWARD_WEIGHTS["picked_up"]
        if fb.applied:
            self.store.log_feedback(sid, rec_id, "applied", 1.0)
            r += REWARD_WEIGHTS["applied"]
        if fb.rating is not None:
            norm = (fb.rating - 1) / 4
            self.store.log_feedback(sid, rec_id, "rating", float(fb.rating))
            r += REWARD_WEIGHTS["rating"] * norm
        if fb.purchased:
            self.store.log_feedback(sid, rec_id, "purchased", 1.0)
            r += REWARD_WEIGHTS["purchased"]
        return round(min(1.0, r), 4)
