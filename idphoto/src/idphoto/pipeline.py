"""전체 파이프라인 오케스트레이터.

주문 1건 = 업로드 → 게이팅 → 참조 임베딩 → 생성 N장 → 규격 크롭 → 후처리
→ QA → 다양성 선발 → 표시 메타데이터.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import gating, prompts, provenance, qa
from .config import Config, DEFAULT
from .detect import FaceAnalyzer
from .framing import frame_to_spec
from .generate import GenerationRequest, get_provider
from .generate.models import ModelSpec, resolve as resolve_models
from .identity import IdentityEncoder
from . import retouch as retouch_mod
from .retouch import RetouchSettings
from .specs import PhotoSpec, get_spec


@dataclass
class OrderResult:
    order_id: str
    spec: PhotoSpec
    provider: str
    model: str
    gates: list[gating.GateResult] = field(default_factory=list)
    candidates: list[qa.Candidate] = field(default_factory=list)
    selected: list[qa.Candidate] = field(default_factory=list)
    reference_spread: float = 0.0
    cost_usd: float = 0.0
    usage: dict = field(default_factory=dict)   # 프로바이더가 보고한 실제 토큰 사용량
    elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        s = qa.summarize(self.candidates)
        s.update(order_id=self.order_id, spec=self.spec.key,
                 provider=self.provider, model=self.model,
                 presented=len(self.selected),
                 reference_spread=round(self.reference_spread, 4),
                 cost_usd=round(self.cost_usd, 4),
                 elapsed_s=round(self.elapsed_s, 2),
                 errors=self.errors[:5])
        return s


class Pipeline:
    def __init__(self, provider: str = "mock", config: Config | None = None,
                 model: str | None = None, models: list[str] | None = None,
                 **provider_kwargs):
        self.cfg = config or DEFAULT
        self.analyzer = FaceAnalyzer()
        self.encoder = IdentityEncoder()
        self._kw = dict(provider_kwargs)
        self._provider_name = provider
        if provider == "mock":
            self._kw.setdefault("analyzer", self.analyzer)

        # 모델 하나 또는 여러 개. 여러 개면 생성을 라운드로빈으로 나눈다.
        self.specs: list[ModelSpec] = []
        if provider != "mock":
            names = models or ([model] if model else None)
            self.specs = resolve_models(names)

        self._providers = {}
        if self.specs:
            for s in self.specs:
                self._providers[s.id] = get_provider(provider, **{**self._kw, "model": s.id})
            self.provider = self._providers[self.specs[0].id]
        else:
            if model:
                self._kw["model"] = model
            self.provider = get_provider(provider, **self._kw)

    def _provider_for(self, i: int):
        """i 번째 생성이 쓸 프로바이더. 모델이 여러 개면 라운드로빈."""
        if not self.specs:
            return self.provider
        return self._providers[self.specs[i % len(self.specs)].id]

    # ---- S0~S2 -------------------------------------------------------
    def prepare(self, images: list[np.ndarray]) -> tuple[np.ndarray, tuple, list, float]:
        """게이팅 → 참조 임베딩. (reference, ref_skin_lab, gates, spread) 반환."""
        gates, embeddings, skin = [], [], []
        for img in images:
            faces = self.analyzer.analyze(img)
            g = gating.evaluate(img, faces, self.cfg.gate)
            gates.append(g)
            if g.usable and g.face is not None:
                embeddings.append(self.encoder.embed(img, g.face))
                skin.append(qa._skin_lab(img, g.face))

        if len(embeddings) < self.cfg.gate.min_usable_photos:
            raise ValueError(
                "쓸 수 있는 사진이 없습니다: "
                + " / ".join(m for g in gates for m in g.coaching()))

        spread = self.encoder.spread(embeddings)
        ref_skin = tuple(float(np.median([s[i] for s in skin])) for i in range(3))
        return self.encoder.reference(embeddings), ref_skin, gates, spread

    # ---- S3~S9 -------------------------------------------------------
    def run(self, images: list[np.ndarray], spec_key: str = "id_kr",
            n_generate: int | None = None, n_present: int | None = None,
            retouch: float = 0.5, seed: int = 0,
            presets: list[prompts.Preset] | None = None) -> OrderResult:
        t0 = time.perf_counter()
        spec = get_spec(spec_key)
        n_gen = n_generate or self.cfg.qa.n_generate
        n_out = n_present or self.cfg.qa.n_present

        res = OrderResult(order_id=uuid.uuid4().hex[:12], spec=spec,
                          provider=self.provider.name,
                 model=",".join(s.id for s in self.specs) or self.provider.model)

        reference, ref_skin, res.gates, res.reference_spread = self.prepare(images)
        if res.reference_spread < self.cfg.gate.reference_spread_min:
            res.errors.append(
                f"참조 사진들의 유사도가 낮습니다 ({res.reference_spread:.3f}) — "
                "서로 다른 사람의 사진이 섞였을 수 있습니다")

        grid = presets or prompts.grid()
        usable = [g.face for g in res.gates if g.usable and g.face]
        refs = [img for img, g in zip(images, res.gates) if g.usable]

        for i in range(n_gen):
            preset = grid[i % len(grid)]
            provider = self._provider_for(i)
            gen = provider.generate(GenerationRequest(
                references=refs, preset=preset, prompt=prompts.build(preset),
                seed=seed + i))
            res.cost_usd += gen.cost_usd
            for k, v in (gen.meta.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    res.usage[k] = res.usage.get(k, 0) + v
            if not gen.ok:
                res.errors.append(f"[{preset.key}] {gen.error}")
                continue

            cand = self._postprocess(gen.image, preset, spec, retouch, seed + i,
                                     f"{res.order_id}-{i:03d}")
            if cand is not None:
                cand.model = gen.model
                res.candidates.append(
                    qa.evaluate(cand, reference, ref_skin, self.cfg.qa))

        res.selected = qa.select(res.candidates, n_out, self.cfg.qa)
        res.elapsed_s = time.perf_counter() - t0
        return res

    def _retouch_settings(self, intensity: float) -> RetouchSettings:
        factory = getattr(RetouchSettings, self.cfg.retouch_preset,
                          RetouchSettings.for_generated)
        return factory(intensity)

    def _postprocess(self, img: np.ndarray, preset, spec: PhotoSpec,
                     retouch: float, seed: int, vid: str) -> qa.Candidate | None:
        """S8 규격 크롭 → S7 리터칭(예산 가드) → 재분석 → 임베딩."""
        faces = self.analyzer.analyze(img)
        if not faces or faces[0].crown is None:
            return None
        try:
            framed = frame_to_spec(img, faces[0], spec)
        except ValueError:
            return None

        refaces = self.analyzer.analyze(framed.image)
        if not refaces:
            return None
        pre_emb = self.encoder.embed(framed.image, refaces[0])

        def measure(candidate: np.ndarray) -> float:
            """리터칭이 유사도를 얼마나 깎았는지. 리터칭 직전 대비로 잰다."""
            g = self.analyzer.analyze(candidate)
            if not g:
                return -1.0
            return self.encoder.cosine(pre_emb,
                                       self.encoder.embed(candidate, g[0])) - 1.0

        final, rep, delta, factor = retouch_mod.apply_within_budget(
            framed.image, refaces[0], measure,
            settings=self._retouch_settings(retouch),
            budget=self.cfg.identity_budget, seed=seed)

        post = self.analyzer.analyze(final)
        if not post:
            return None
        cand = qa.Candidate(
            variant_id=vid, image=final, preset=preset.as_dict(),
            face=post[0], embedding=self.encoder.embed(final, post[0]),
            framing=framed)
        cand.retouch_delta = delta
        cand.retouch_factor = factor
        cand.blemishes_removed = rep.blemishes.count
        return cand

    # ---- 딜리버리 ----------------------------------------------------
    def deliver(self, res: OrderResult, out_dir: str | Path,
                preview: bool = False) -> list[str]:
        """선발된 결과를 AI 생성 표시와 함께 저장한다."""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for rank, cand in enumerate(res.selected, 1):
            rec = provenance.disclosure_record(
                provider=res.provider, model=res.model, spec=res.spec.key,
                preset=cand.preset, order_id=res.order_id)
            rec["id_similarity"] = round(cand.id_cos, 4)
            img = provenance.watermark_preview(cand.image) if preview else cand.image
            p = out_dir / f"{res.order_id}_{rank:02d}_{cand.variant_id}.jpg"
            provenance.write_jpeg(str(p), img, rec)
            paths.append(str(p))
        return paths
