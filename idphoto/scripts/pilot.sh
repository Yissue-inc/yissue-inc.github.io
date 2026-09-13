#!/usr/bin/env bash
# 파일럿 1장 → 실제 비용 실측 → 붙여넣을 JSON 출력.
#
# 사용법:  ./scripts/pilot.sh 사진1.jpg 사진2.jpg 사진3.jpg
#
# 키는 ai_keys.py 로만 받는다. 이 스크립트는 키 값을 보지도, 남기지도 않는다.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ $# -ge 1 ] || { echo "사용법: $0 <사진...>" >&2; exit 1; }

# --- ai_keys.py 찾기 ---
AI_KEYS=""
for c in \
  "$HOME/work/yissue_brain/Hermes/automation/ai_keys.py" \
  "$HOME/yissue_brain/Hermes/automation/ai_keys.py" \
  "$HOME/work/Yissue_Brain/Hermes/automation/ai_keys.py" \
  "${YISSUE_BRAIN:-}/Hermes/automation/ai_keys.py" ; do
  [ -f "$c" ] && { AI_KEYS="$c"; break; }
done
if [ -z "$AI_KEYS" ]; then
  echo "ai_keys.py 를 찾지 못했습니다." >&2
  echo "  YISSUE_BRAIN=/path/to/yissue_brain $0 $*" >&2
  exit 2
fi
echo "ai_keys: $AI_KEYS" >&2

# --- 의존성 (최초 1회만 실제로 설치됨) ---
python3 -m pip install -q -r requirements.txt
./scripts/fetch_models.sh >&2

# --- 파일럿 1장 ---
# 공시가 $0.067/장 기준 상한. 실측치는 아래 출력의 est_usd_next_run 에 나온다.
PYTHONPATH=src python3 "$AI_KEYS" run gemini \
  --purpose "AI 증명사진 파이프라인 파일럿 1장" \
  --est-usd 0.08 --model gemini-3.1-flash-image \
  -- python3 -m idphoto run "$@" \
       --provider gemini --model gemini-3.1-flash-image \
       --spec id_kr --n 1 --present 1 --out out/pilot

echo >&2
echo "── 위 JSON 전체를 Claude 에게 붙여넣어 주세요 ──" >&2
echo "   out/pilot/ 의 결과 이미지도 함께 주시면 품질 비교까지 가능합니다." >&2
