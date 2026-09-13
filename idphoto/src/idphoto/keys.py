"""AI API 키 획득 — Hermes `ai_keys.py` 프로토콜 브리지.

**키 파일을 직접 읽지 않는다.** 키는 `Hermes/automation/ai_keys.py` 한 곳에서만
받는다. 그 도구가 환경 판별·운영키 거부·금액 기준·원장 기록을 담당한다.

이 모듈은 얇은 어댑터일 뿐이다. `ai_keys.require()` 가 `os.environ` 을 채우면
`generate/gemini.py` 가 평소처럼 그걸 읽는다 — 키가 이 코드를 통과하지 않는다.

경로:
  1. `ai_keys.py` 가 보이면 그것으로 받는다 (CK 로컬 맥, VPS 컨테이너)
  2. 안 보이면 환경변수에 이미 있는지만 본다 (클라우드 에이전트 — 환경 시크릿)
  3. 둘 다 없으면 **멈추고 해결 방법을 안내한다.** 채팅으로 키를 요청하지 않는다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: 별칭 → 환경변수 이름
ENV_VAR = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}

#: ai_keys.py 를 찾을 후보 경로
_SEARCH = (
    "Hermes/automation",
    "../Hermes/automation",
    "../../Hermes/automation",
    "~/yissue_brain/Hermes/automation",
    "~/work/yissue_brain/Hermes/automation",
)


class KeyUnavailable(RuntimeError):
    """키를 얻지 못했다. 메시지에 환경별 해결 방법이 들어 있다."""


def _find_ai_keys() -> Path | None:
    for c in _SEARCH:
        p = Path(os.path.expanduser(c)) / "ai_keys.py"
        if p.is_file():
            return p.parent
    return None


def acquire(alias: str = "gemini", *, purpose: str, est_usd: float,
            model: str | None = None, approval: str | None = None) -> str:
    """키를 확보하고 출처 문자열을 돌려준다. 키 값은 반환하지 않는다.

    성공하면 `os.environ[ENV_VAR[alias]]` 가 채워져 있다.
    """
    var = ENV_VAR.get(alias, f"{alias.upper()}_API_KEY")

    tool_dir = _find_ai_keys()
    if tool_dir is not None:
        sys.path.insert(0, str(tool_dir))
        try:
            from ai_keys import require           # type: ignore
        except ImportError as exc:
            raise KeyUnavailable(f"ai_keys.py 를 찾았으나 임포트 실패: {exc}") from None
        kwargs = dict(purpose=purpose, est_usd=est_usd)
        if model:
            kwargs["model"] = model
        if approval:
            kwargs["approval"] = approval
        job = require(alias, **kwargs)
        return f"ai_keys({alias}) job={job}"

    if os.environ.get(var):
        # 클라우드 에이전트: 환경 시크릿에 등록된 경우
        return f"환경변수 {var}"

    raise KeyUnavailable(
        f"'{alias}' 키를 얻지 못했습니다.\n"
        f"\n"
        f"  ai_keys.py 를 찾지 못했고 {var} 환경변수도 비어 있습니다.\n"
        f"  현재 환경: 클라우드 에이전트(GitHub 클론)로 보입니다 — 저장소에 키가\n"
        f"  없는 것이 정상입니다.\n"
        f"\n"
        f"  해결 방법 두 가지:\n"
        f"   1) 이 실행 환경의 환경 시크릿에 {var} 를 등록한다\n"
        f"      (운영 키가 아닌, 한도를 건 작업 전용 키만)\n"
        f"   2) 유료 호출 단계만 CK 로컬 에이전트로 넘긴다 —\n"
        f"      코드·계획·예상 비용은 여기서 만들어 두고 실행만 로컬에서\n"
        f"\n"
        f"  키를 채팅에 붙여 달라고 요청하지 않습니다.")
