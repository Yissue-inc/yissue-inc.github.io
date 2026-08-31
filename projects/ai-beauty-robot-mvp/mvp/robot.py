"""로봇팔 드라이버.

⚠️ 이 레이어의 유일한 규칙: **로봇은 '슬롯 번호'만 안다.**
   인지·판단·추천은 전부 상위 레이어의 몫입니다. 이 파일에 비즈니스 로직이 들어오면
   나중에 로봇을 교체할 때 프로젝트 전체를 다시 써야 합니다.

궤적은 7단계 고정입니다 (L1 = 티칭 좌표 재생):
    home → approach(슬롯 위 100mm) → descend → grip → lift → move_to_chute → release → home
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

SLOTS_FILE = Path(__file__).parent / "data" / "slots.json"


@dataclass
class PickResult:
    ok: bool
    slot_id: int
    duration_ms: int
    retry_count: int = 0
    error_code: str | None = None


class RobotError(RuntimeError):
    pass


class RobotArm:
    """모든 로봇 백엔드가 구현하는 인터페이스."""

    name = "base"

    def connect(self) -> None: raise NotImplementedError
    def disconnect(self) -> None: raise NotImplementedError
    def home(self) -> None: raise NotImplementedError
    def estop(self) -> None: raise NotImplementedError
    def door_closed(self) -> bool: return True
    def pick_and_deliver(self, slot_id: int, grip_force: int = 50) -> PickResult:
        raise NotImplementedError


class MockArm(RobotArm):
    """하드웨어 없이 개발하기 위한 시뮬레이터.

    협동로봇 리드타임은 4~8주입니다. 그동안 이걸로 앱 전체를 완성하세요.
    `failure_rate` 를 0.05 로 올려두고 개발하면 실패 처리 코드를 반드시 짜게 됩니다.
    """

    name = "mock"

    def __init__(self, cycle_s: float = 0.15, failure_rate: float = 0.03,
                 seed: int | None = None, realtime: bool = False):
        self.cycle_s = cycle_s
        self.failure_rate = failure_rate
        self.rng = random.Random(seed)
        self.realtime = realtime
        self.connected = False
        self.door = True
        self.log: list[str] = []

    def connect(self) -> None:
        self.connected = True
        self.log.append("connect")

    def disconnect(self) -> None:
        self.connected = False
        self.log.append("disconnect")

    def home(self) -> None:
        self._require()
        self.log.append("home")

    def estop(self) -> None:
        self.log.append("ESTOP")
        self.connected = False

    def door_closed(self) -> bool:
        return self.door

    def _require(self) -> None:
        if not self.connected:
            raise RobotError("robot not connected")
        if not self.door_closed():
            raise RobotError("door open — 안전 인터락")

    def pick_and_deliver(self, slot_id: int, grip_force: int = 50) -> PickResult:
        self._require()
        t0 = time.time()
        retries = 0
        for attempt in range(2):          # 실패 시 1회 재시도, 2회 실패면 직원 호출
            for step in ("approach", "descend", "grip", "lift", "move_to_chute", "release"):
                if self.realtime:
                    time.sleep(self.cycle_s / 6)
                self.log.append(f"slot{slot_id}:{step}")
            if self.rng.random() >= self.failure_rate:
                return PickResult(True, slot_id, int((time.time() - t0) * 1000), retries)
            retries += 1
            self.log.append(f"slot{slot_id}:GRIP_FAIL")
        self.home()
        return PickResult(False, slot_id, int((time.time() - t0) * 1000), retries, "GRIP_FAILED")


# --------------------------------------------------------------------------
# 실장비 드라이버 스켈레톤 — 팔이 도착하면 여기만 채우면 됩니다.
# --------------------------------------------------------------------------

class TeachedSlotArm(RobotArm):
    """티칭된 슬롯 좌표(slots.json)를 재생하는 실장비 공통 베이스.

    slots.json 만드는 법 (Week 4, 약 20분):
      1. 로봇을 프리드라이브(드래그 티칭) 모드로 전환
      2. 손으로 잡고 슬롯 1의 파지 자세로 끌고 감
      3. 현재 TCP 포즈를 읽어 저장  →  20슬롯 반복
    형식: {"slots": {"1": {"pose": [x,y,z,rx,ry,rz], "approach_dz": 100}, ...},
           "chute": {"pose": [...]}, "home": {"pose": [...]}}
    """

    def __init__(self, slots_file: Path | str = SLOTS_FILE, speed_mms: float = 200.0):
        self.slots_file = Path(slots_file)
        self.speed_mms = min(speed_mms, 250.0)   # 매장 모드 하드 리밋 (ISO/TS 15066 참고)
        self.slots: dict = {}

    def load_slots(self) -> None:
        if not self.slots_file.exists():
            raise RobotError(f"{self.slots_file} 없음 — Week 4 티칭 과제를 먼저 끝내세요")
        self.slots = json.loads(self.slots_file.read_text())

    # 하위 클래스가 구현할 원시 동작
    def move_l(self, pose: list[float]) -> None: raise NotImplementedError
    def set_gripper(self, opening: int, force: int) -> None: raise NotImplementedError
    def gripped(self) -> bool: raise NotImplementedError

    def pick_and_deliver(self, slot_id: int, grip_force: int = 50) -> PickResult:
        t0, retries = time.time(), 0
        slot = self.slots["slots"][str(slot_id)]
        pose, dz = list(slot["pose"]), slot.get("approach_dz", 100)
        above = pose[:2] + [pose[2] + dz] + pose[3:]
        for _ in range(2):
            self.move_l(above)
            self.set_gripper(100, grip_force)
            self.move_l(pose)
            self.set_gripper(0, grip_force)
            self.move_l(above)
            if self.gripped():                       # 파지 검증 — 이거 없으면 빈 손으로 배출합니다
                self.move_l(self.slots["chute"]["pose"])
                self.set_gripper(100, grip_force)
                self.move_l(self.slots["home"]["pose"])
                return PickResult(True, slot_id, int((time.time() - t0) * 1000), retries)
            retries += 1
        self.move_l(self.slots["home"]["pose"])
        return PickResult(False, slot_id, int((time.time() - t0) * 1000), retries, "GRIP_FAILED")


class MyCobotArm(TeachedSlotArm):
    """Elephant Robotics myCobot 280/320.

        pip install pymycobot
        from pymycobot.mycobot import MyCobot
        mc = MyCobot("/dev/ttyUSB0", 115200)
        mc.send_coords([x, y, z, rx, ry, rz], speed, mode)   # mode 1 = 직선
        mc.set_gripper_value(value, speed)                   # 0=닫힘 100=열림
    """
    name = "mycobot"


class XArmArm(TeachedSlotArm):
    """UFACTORY Lite 6 / xArm 6.

        pip install xarm-python-sdk
        from xarm.wrapper import XArmAPI
        arm = XArmAPI("192.168.1.xxx")
        arm.motion_enable(True); arm.set_mode(0); arm.set_state(0)
        arm.set_position(x=.., y=.., z=.., roll=.., pitch=.., yaw=.., speed=200, wait=True)
        arm.set_gripper_position(pos, wait=True)
        code, states = arm.get_gripper_position()   # 파지 검증에 사용
    """
    name = "xarm"


class DobotArm(TeachedSlotArm):
    """Dobot MG400 (4축 SCARA). top-down 픽만 필요하면 6축보다 빠르고 안 흔들립니다.

        TCP/IP Dashboard(29999) + Move(30003) 포트로 제어.
        MovL(x, y, z, r) / DO(index, status) 로 그리퍼 제어.
    """
    name = "dobot_mg400"
