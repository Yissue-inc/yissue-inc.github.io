# 모델 라이선스 (2026-09-13 원본 확인)

| 파일 | 출처 | 라이선스 | 상용 |
|---|---|---|---|
| `yunet_2023mar.onnx` | opencv/opencv_zoo `face_detection_yunet` | Apache-2.0 | ✅ |
| `sface_2021dec.onnx` | opencv/opencv_zoo `face_recognition_sface` | Apache-2.0 | ✅ |
| `face_landmarker.task` | google-ai-edge/mediapipe | Apache-2.0 | ✅ |

## 의도적으로 배제한 모델

| 모델 | 라이선스 | 사유 |
|---|---|---|
| InsightFace 사전학습 전체 (`buffalo_l`, `antelopev2`, `inswapper_128` …) | non-commercial research only | 코드는 MIT지만 **auto-download 모델 포함 전부** 비상업. upstream README §License 명시 |
| CodeFormer | S-Lab License 1.0 | "non-commercial purpose" 명문 |
| BRIA RMBG-2.0 | BRIA 상용 유료 | 상용 시 별도 계약 |

상용 대체재: 얼굴 인식 = SFace(Apache-2.0), 매팅 = BiRefNet(MIT), 복원 = GFPGAN(Apache-2.0), 리라이팅 = IC-Light(Apache-2.0).
