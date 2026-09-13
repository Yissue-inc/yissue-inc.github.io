"""얼굴 기하 정보 — 검출기·랜드마커가 공통으로 채우는 자료구조."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


Point = tuple[float, float]


@dataclass
class FaceGeometry:
    """한 얼굴의 기하. 좌표는 모두 원본 이미지 픽셀 기준."""

    box: tuple[float, float, float, float]      # x, y, w, h
    right_eye: Point                            # 피사체 기준 오른쪽 눈 (이미지 왼쪽)
    left_eye: Point
    nose: Point
    mouth_right: Point
    mouth_left: Point
    score: float
    raw: object = None                          # 검출기 원시 행 (SFace alignCrop용)

    chin: Point | None = None                   # 턱끝
    crown: Point | None = None                  # 정수리 (머리카락 포함)
    crown_source: str = "none"                  # matte | landmark | none
    landmarks: list[Point] = field(default_factory=list)

    # --- 파생값 ---
    @property
    def eye_mid(self) -> Point:
        return ((self.right_eye[0] + self.left_eye[0]) / 2,
                (self.right_eye[1] + self.left_eye[1]) / 2)

    @property
    def eye_distance(self) -> float:
        return math.dist(self.right_eye, self.left_eye)

    @property
    def roll_deg(self) -> float:
        """눈선 기울기. 양수면 이미지가 시계방향으로 기울어 있다."""
        dx = self.left_eye[0] - self.right_eye[0]
        dy = self.left_eye[1] - self.right_eye[1]
        return math.degrees(math.atan2(dy, dx))

    @property
    def yaw_proxy(self) -> float:
        """좌우 회전 근사치(-1..1). 눈 중점 대비 코끝의 수평 편차를 눈 간격으로 정규화.

        정확한 6DoF 포즈가 아니라 게이팅용 프록시다. 0이 정면.
        """
        if self.eye_distance < 1e-6:
            return 0.0
        return (self.nose[0] - self.eye_mid[0]) / self.eye_distance

    @property
    def pitch_proxy(self) -> float:
        """상하 회전 근사치. 눈-입 거리 대비 눈-코 거리 비율의 정면 기준 편차."""
        mouth_mid = ((self.mouth_right[0] + self.mouth_left[0]) / 2,
                     (self.mouth_right[1] + self.mouth_left[1]) / 2)
        eye_to_mouth = math.dist(self.eye_mid, mouth_mid)
        if eye_to_mouth < 1e-6:
            return 0.0
        eye_to_nose = math.dist(self.eye_mid, self.nose)
        # 정면 성인 얼굴에서 eye→nose / eye→mouth ≈ 0.62
        return (eye_to_nose / eye_to_mouth) - 0.62

    @property
    def head_height(self) -> float | None:
        """정수리~턱끝 픽셀 거리. crown/chin이 모두 있을 때만."""
        if self.chin is None or self.crown is None:
            return None
        return abs(self.chin[1] - self.crown[1])

    @property
    def face_axis_x(self) -> float:
        """얼굴 수직축의 x 좌표. 눈 중점과 턱(있으면)의 평균."""
        if self.chin is not None:
            return (self.eye_mid[0] + self.chin[0]) / 2
        return self.eye_mid[0]
