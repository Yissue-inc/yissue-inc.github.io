"""제품 카탈로그 로더."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).parent / "data" / "products.json"


@dataclass
class Product:
    id: str
    brand: str
    name: str
    category: str
    cluster: str
    concerns: list[str]
    skin_types: list[str]
    price: int
    price_band: str
    slot_id: int
    grip_force: int
    form: str
    stock: int = 0

    @property
    def label(self) -> str:
        return f"{self.brand} {self.name}"


@dataclass
class Catalog:
    products: list[Product]
    clusters: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str = DATA) -> "Catalog":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        keys = Product.__dataclass_fields__.keys()
        items = [Product(**{k: v for k, v in p.items() if k in keys}) for p in raw["products"]]
        return cls(products=items, clusters=raw.get("clusters", {}))

    def by_id(self, pid: str) -> Product:
        return next(p for p in self.products if p.id == pid)

    def by_cluster(self, cluster: str, in_stock_only: bool = True) -> list[Product]:
        return [p for p in self.products
                if p.cluster == cluster and (p.stock > 0 or not in_stock_only)]

    @property
    def cluster_ids(self) -> list[str]:
        return sorted(self.clusters) or sorted({p.cluster for p in self.products})
