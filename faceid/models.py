"""Download and cache the two OpenCV Zoo ONNX models we need.

YuNet (face detection) and SFace (face recognition/embedding) are both
tiny (<40MB combined), MIT/permissive-licensed, and ship no native
compiler dependency -- they run through cv2.FaceDetectorYN /
cv2.FaceRecognizerSF. This avoids dlib / TensorFlow build headaches on
Windows, which is the whole reason they were chosen for a same-day build.
"""
from __future__ import annotations

import pathlib
import sys

import requests

MODELS_DIR = pathlib.Path(__file__).resolve().parent.parent / "models"

# Pinned to specific commits in opencv/opencv_zoo so the file contents
# (and therefore behavior) can't silently change under us.
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
SFACE_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_recognition_sface/face_recognition_sface_2021dec.onnx"
)

YUNET_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_PATH = MODELS_DIR / "face_recognition_sface_2021dec.onnx"


def _download(url: str, dest: pathlib.Path) -> None:
    if dest.exists() and dest.stat().st_size > 1024:
        return
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[models] downloading {dest.name} ...", file=sys.stderr)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    print(f"[models] saved {dest} ({len(resp.content)} bytes)", file=sys.stderr)


def ensure_models() -> tuple[pathlib.Path, pathlib.Path]:
    """Ensure both ONNX models are present locally; return their paths."""
    _download(YUNET_URL, YUNET_PATH)
    _download(SFACE_URL, SFACE_PATH)
    return YUNET_PATH, SFACE_PATH


if __name__ == "__main__":
    yunet, sface = ensure_models()
    print(f"YuNet: {yunet}")
    print(f"SFace: {sface}")
