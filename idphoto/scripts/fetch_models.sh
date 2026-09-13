#!/usr/bin/env bash
# Downloads model weights. All Apache-2.0 — see models/LICENSES.md.
set -euo pipefail
D="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/models"
mkdir -p "$D"
ZOO=https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models
MPM=https://storage.googleapis.com/mediapipe-models

get(){ [ -s "$D/$2" ] && { echo "  have $2"; return; }
       echo "  get  $2"; curl -sSL --max-time 300 -o "$D/$2" "$1"; }

get "$ZOO/face_detection_yunet/face_detection_yunet_2023mar.onnx"   yunet_2023mar.onnx
get "$ZOO/face_recognition_sface/face_recognition_sface_2021dec.onnx" sface_2021dec.onnx
get "$MPM/face_landmarker/face_landmarker/float16/1/face_landmarker.task" face_landmarker.task
echo "done -> $D"
