"""로컬 로그 저장소 (SQLite).

⚠️ 이 파일이 이 프로젝트에서 **가장 중요한 파일**입니다.
   로봇팔은 눈에 띄는 부분이고, 자산은 여기 쌓이는 데이터입니다.
   PLAN.md 7장의 스키마와 1:1로 대응합니다.

개인정보 원칙 (설계로 지킵니다):
  * 이름/연락처 컬럼이 아예 없습니다. 없으면 유출도 없습니다.
  * 원본 얼굴 이미지는 저장하지 않습니다(image_ref 는 별도 동의 시에만 채웁니다).
  * 연령은 '대'로만, 성별은 수집하지 않습니다.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

DDL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS session (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  store_id TEXT,
  device_id TEXT,
  consent_personal INTEGER NOT NULL DEFAULT 0,
  consent_biometric INTEGER NOT NULL DEFAULT 0,
  staff_intervened INTEGER NOT NULL DEFAULT 0,
  exit_stage TEXT,
  policy_version TEXT,
  schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS skin_measurement (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES session(id),
  captured_at TEXT NOT NULL,
  metrics TEXT NOT NULL,
  capture_quality REAL,
  image_ref TEXT,
  analyzer TEXT,
  analyzer_version TEXT
);

CREATE TABLE IF NOT EXISTS survey (
  session_id TEXT PRIMARY KEY REFERENCES session(id),
  age_band TEXT, skin_type TEXT, budget_band TEXT,
  concerns TEXT, allergies TEXT, current_products TEXT
);

CREATE TABLE IF NOT EXISTS recommendation (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES session(id),
  product_id TEXT NOT NULL,
  cluster TEXT NOT NULL,
  rank INTEGER NOT NULL,
  deliver_order INTEGER,          -- 전달 순서 편향 보정용. rank 와 다를 수 있음(랜덤화)
  score REAL,
  is_exploration INTEGER NOT NULL DEFAULT 0,
  policy_version TEXT,
  features TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS robot_action (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES session(id),
  product_id TEXT, slot_id INTEGER, action TEXT,
  success INTEGER, duration_ms INTEGER, retry_count INTEGER, error_code TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES session(id),
  recommendation_id TEXT REFERENCES recommendation(id),
  kind TEXT NOT NULL,             -- picked_up | applied | rating | purchased | skipped
  value REAL NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rec_session ON recommendation(session_id);
CREATE INDEX IF NOT EXISTS idx_fb_session  ON feedback(session_id);
CREATE INDEX IF NOT EXISTS idx_fb_rec      ON feedback(recommendation_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


class Store:
    def __init__(self, path: str | Path = "kiosk.db"):
        self.path = str(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(DDL)
        self.conn.commit()

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---- writes
    def start_session(self, *, store_id: str, device_id: str, consent_personal: bool,
                      consent_biometric: bool, policy_version: str) -> str:
        sid = new_id()
        with self.tx() as c:
            c.execute(
                "INSERT INTO session (id, started_at, store_id, device_id, consent_personal,"
                " consent_biometric, policy_version, schema_version) VALUES (?,?,?,?,?,?,?,?)",
                (sid, now(), store_id, device_id, int(consent_personal),
                 int(consent_biometric), policy_version, SCHEMA_VERSION))
        return sid

    def end_session(self, sid: str, exit_stage: str, staff_intervened: bool = False) -> None:
        with self.tx() as c:
            c.execute("UPDATE session SET ended_at=?, exit_stage=?, staff_intervened=? WHERE id=?",
                      (now(), exit_stage, int(staff_intervened), sid))

    def log_measurement(self, sid: str, m) -> str:
        mid = new_id()
        with self.tx() as c:
            c.execute("INSERT INTO skin_measurement VALUES (?,?,?,?,?,?,?,?)",
                      (mid, sid, now(), json.dumps(m.metrics, ensure_ascii=False),
                       m.quality, m.image_ref, m.analyzer, m.analyzer_version))
        return mid

    def log_survey(self, sid: str, p) -> None:
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO survey VALUES (?,?,?,?,?,?,?)",
                      (sid, p.age_band, p.skin_type, p.budget_band,
                       json.dumps(p.self_concerns, ensure_ascii=False), "[]", "[]"))

    def log_recommendation(self, sid: str, rec, features: list[float],
                           policy_version: str, deliver_order: int) -> str:
        rid = new_id()
        with self.tx() as c:
            c.execute("INSERT INTO recommendation VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (rid, sid, rec.product.id, rec.cluster, rec.rank, deliver_order,
                       rec.score, int(rec.is_exploration), policy_version,
                       json.dumps(features), now()))
        return rid

    def log_robot(self, sid: str, product_id: str, result, action: str = "pick_and_deliver") -> None:
        with self.tx() as c:
            c.execute("INSERT INTO robot_action VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (new_id(), sid, product_id, result.slot_id, action, int(result.ok),
                       result.duration_ms, result.retry_count, result.error_code, now()))

    def log_feedback(self, sid: str, rec_id: str | None, kind: str, value: float) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO feedback VALUES (?,?,?,?,?,?)",
                      (new_id(), sid, rec_id, kind, float(value), now()))

    # ---- reads (분석/학습 배치용)
    def acceptance_rate(self, policy_version: str | None = None) -> tuple[int, int]:
        q = ("SELECT COUNT(*) AS n,"
             " SUM(CASE WHEN EXISTS (SELECT 1 FROM feedback f WHERE f.recommendation_id=r.id"
             "   AND f.kind='picked_up' AND f.value>0) THEN 1 ELSE 0 END) AS acc"
             " FROM recommendation r")
        args: tuple = ()
        if policy_version:
            q += " WHERE r.policy_version=?"
            args = (policy_version,)
        row = self.conn.execute(q, args).fetchone()
        return int(row["acc"] or 0), int(row["n"] or 0)

    def robot_success_rate(self) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT COUNT(*) n, SUM(success) ok FROM robot_action").fetchone()
        return int(row["ok"] or 0), int(row["n"] or 0)

    def close(self) -> None:
        self.conn.close()
