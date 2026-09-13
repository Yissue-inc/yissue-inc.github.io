"""모든 임계값을 한 곳에. 품질을 '조이는' 작업은 전부 이 파일에서 일어난다.

각 값에는 근거와 튜닝 방향을 적어 둔다. 실사용 클레임률이 쌓이면
docs/thresholds.md 에 측정치를 기록하고 여기 값을 갱신한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GateConfig:
    """S0 — 입력 게이팅. 생성 전에 거르는 편이 생성 후 고치는 것보다 싸다."""

    # 얼굴 크기: 짧은 변 픽셀. 이보다 작으면 복원해도 디테일이 없다.
    face_min_px: int = 200
    face_warn_px: int = 400

    # 선명도: 얼굴 ROI를 256px로 맞춘 뒤 잰 라플라시안 분산.
    # 2026-09-13 보정 (samples/public, gating._lap_var):
    #   선명한 원본 283 / 가우시안 k=3 85 / k=5 43 / k=9 16 / k=15 7
    #   저해상 업스케일: 얼굴 69px→108, 38px→19, 23px→4
    # k=5 이상 블러와 40px 이하 얼굴은 복원해도 못 쓴다 → reject 25.
    # 실제 휴대폰 셀카는 이보다 훨씬 높게 나오므로, 사용자 실사진이 모이면 재보정할 것.
    sharpness_reject: float = 25.0
    sharpness_warn: float = 80.0

    # 포즈 프록시 (geometry.py 정의). 증명사진은 정면이어야 한다.
    yaw_reject: float = 0.30
    yaw_warn: float = 0.16
    pitch_reject: float = 0.16
    pitch_warn: float = 0.09
    roll_reject_deg: float = 25.0
    roll_warn_deg: float = 12.0

    # 눈 뜬 정도 (EAR). 감은 눈은 증명사진 즉시 반려 사유다.
    ear_reject: float = 0.14
    ear_warn: float = 0.19

    # 노출: 얼굴 영역 평균 휘도(0..255)와 클리핑 비율
    luma_low: float = 55.0
    luma_high: float = 205.0
    clip_warn: float = 0.06

    # 안경 반사: 눈 주변 하이라이트 클리핑 비율
    glare_warn: float = 0.08

    # 참조 사진 간 최소 유사도. 이보다 낮으면 다른 사람이 섞여 있다.
    reference_spread_min: float = 0.28

    min_usable_photos: int = 1


@dataclass(frozen=True)
class QAConfig:
    """S9 — 생성 결과 QA. 하드 게이트를 통과한 후보만 랭킹한다."""

    # 본인 같음. SFace 레퍼런스 동일인 임계값은 0.363이지만, 증명사진은
    # '본인인데 본인 같지 않음' 클레임이 더 크므로 보수적으로 올려 잡는다.
    tau_id: float = 0.42
    tau_id_target: float = 0.55          # 이 이상이면 안심하고 노출

    # 후처리가 유사도를 깎는 폭의 상한. 복원을 세게 걸면 얼굴이 바뀐다.
    max_delta_cos_post: float = 0.05

    # 피부 밝기 이동 상한 (CIE L*). 모델의 톤 밝히기 편향을 잡는다.
    max_skin_delta_L: float = 4.0

    # 스코어 가중치 — 합이 1.0
    w_identity: float = 0.40
    w_quality: float = 0.20
    w_spec: float = 0.15
    w_aesthetic: float = 0.15
    w_neutral: float = 0.10

    # 다양성 선발 (MMR). 1.0이면 순수 점수순, 0에 가까울수록 다양성 우선.
    mmr_lambda: float = 0.72

    n_generate: int = 40
    n_present: int = 5
    max_retry_rounds: int = 2


@dataclass(frozen=True)
class Config:
    gate: GateConfig = field(default_factory=GateConfig)
    qa: QAConfig = field(default_factory=QAConfig)


DEFAULT = Config()
