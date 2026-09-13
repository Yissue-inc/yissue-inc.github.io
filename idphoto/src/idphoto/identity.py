"""S2 / S9 — 아이덴티티 임베딩과 유사도.

SFace (OpenCV Zoo, Apache-2.0). InsightFace buffalo_l 은 사전학습 가중치가
비상업 연구용이라 상용 서비스에 쓸 수 없어 의도적으로 배제했다.

임계값: OpenCV 레퍼런스 구현이 코사인 0.363 을 동일인 판정 기준으로 제시한다.
증명사진은 '타인을 본인으로 오인'보다 '본인인데 본인 같지 않음'이 더 큰
클레임이므로, 서비스 게이트는 이보다 보수적으로 올려 잡는다(config.TAU_ID).
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np

from .geometry import FaceGeometry

MODELS_DIR = Path(os.environ.get(
    "IDPHOTO_MODELS", Path(__file__).resolve().parents[2] / "models"))

#: OpenCV SFace 레퍼런스 동일인 판정 임계값 (코사인)
SFACE_REFERENCE_THRESHOLD = 0.363


class IdentityEncoder:
    def __init__(self, model_path: Path | None = None):
        self.model_path = Path(model_path or MODELS_DIR / "sface_2021dec.onnx")
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"{self.model_path} 없음 — scripts/fetch_models.sh 를 먼저 실행하세요")
        self._net = cv2.FaceRecognizerSF.create(str(self.model_path), "")

    def embed(self, bgr: np.ndarray, geo: FaceGeometry) -> np.ndarray:
        """단위 정규화된 임베딩 벡터를 반환한다."""
        if geo.raw is None:
            raise ValueError("FaceGeometry.raw 가 필요합니다 (YuNet 검출 결과)")
        aligned = self._net.alignCrop(bgr, np.asarray(geo.raw, dtype=np.float32))
        feat = self._net.feature(aligned).flatten().astype(np.float64)
        norm = np.linalg.norm(feat)
        return feat / norm if norm > 0 else feat

    def reference(self, embeddings: list[np.ndarray],
                  drop_outlier: bool = True) -> np.ndarray:
        """참조 사진들의 평균 임베딩.

        업로드 중 한 장이 다른 사람이거나 심하게 흐린 경우가 실제로 흔하다.
        3장 이상이면 중심에서 가장 먼 1장을 버린다.
        """
        if not embeddings:
            raise ValueError("임베딩이 비어 있습니다")
        mat = np.vstack(embeddings)
        if drop_outlier and len(mat) >= 3:
            centroid = _normalize(mat.mean(axis=0))
            sims = mat @ centroid
            mat = np.delete(mat, int(np.argmin(sims)), axis=0)
        return _normalize(mat.mean(axis=0))

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(_normalize(a), _normalize(b)))

    def spread(self, embeddings: list[np.ndarray]) -> float:
        """참조 사진들끼리의 최소 유사도. 낮으면 서로 다른 사람이 섞여 있다."""
        if len(embeddings) < 2:
            return 1.0
        mat = np.vstack([_normalize(e) for e in embeddings])
        sims = mat @ mat.T
        np.fill_diagonal(sims, 1.0)
        return float(sims.min())


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v
