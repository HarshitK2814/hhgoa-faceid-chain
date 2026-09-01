"""Face detection + embedding via OpenCV's YuNet + SFace models.

Public API:
    detect_and_embed(image_path_or_bytes) -> FaceResult | None
    cosine(a, b) -> float
    SFACE_MATCH_THRESHOLD  -- OpenCV's documented default cosine threshold
"""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
from typing import Optional, Union

import cv2
import numpy as np

from .models import ensure_models

# OpenCV's own sample/docs recommend 0.363 as the cosine-similarity
# threshold for "same person" with SFace embeddings.
SFACE_MATCH_THRESHOLD = 0.363


@dataclasses.dataclass
class FaceResult:
    embedding: np.ndarray          # (128,) float32, L2-normalized by SFace
    detect_score: float            # YuNet confidence of the chosen face
    bbox: tuple[int, int, int, int]
    aligned_crop: np.ndarray       # BGR image, the 112x112 aligned crop SFace used
    num_faces_detected: int


_detector: Optional["cv2.FaceDetectorYN"] = None
_recognizer: Optional["cv2.FaceRecognizerSF"] = None


def _get_models():
    global _detector, _recognizer
    if _detector is None or _recognizer is None:
        yunet_path, sface_path = ensure_models()
        _detector = cv2.FaceDetectorYN.create(
            str(yunet_path), "", (320, 320), score_threshold=0.6
        )
        _recognizer = cv2.FaceRecognizerSF.create(str(sface_path), "")
    return _detector, _recognizer


def _load_image(source: Union[str, pathlib.Path, bytes]) -> np.ndarray:
    if isinstance(source, (bytes, bytearray)):
        arr = np.frombuffer(source, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    else:
        img = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not decode image: {source!r}")
    return img


def detect_and_embed(source: Union[str, pathlib.Path, bytes]) -> Optional[FaceResult]:
    """Detect the most confident face in an image and return its SFace embedding.

    Returns None if no face is detected.
    """
    detector, recognizer = _get_models()
    img = _load_image(source)
    h, w = img.shape[:2]
    detector.setInputSize((w, h))
    n, faces = detector.detect(img)
    if faces is None or len(faces) == 0:
        return None

    # faces rows: [x, y, w, h, <5 landmark pairs>, score]
    best_idx = int(np.argmax(faces[:, -1]))
    best = faces[best_idx]
    score = float(best[-1])
    x, y, fw, fh = best[:4].astype(int)

    aligned = recognizer.alignCrop(img, best)
    embedding = recognizer.feature(aligned)  # (1, 128)
    embedding = embedding.flatten().astype(np.float32)

    return FaceResult(
        embedding=embedding,
        detect_score=score,
        bbox=(int(x), int(y), int(fw), int(fh)),
        aligned_crop=aligned,
        num_faces_detected=len(faces),
    )


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def save_crop(face: FaceResult, dest: Union[str, pathlib.Path]) -> None:
    cv2.imwrite(str(dest), face.aligned_crop)


def detect_and_embed_from_url(url: str, requests_get) -> Optional[FaceResult]:
    """Convenience: fetch bytes with a caller-supplied `requests.get`-like
    function and run detect_and_embed on them. Kept separate from face.py's
    core so this module has no direct network dependency of its own.
    """
    resp = requests_get(url, timeout=20)
    resp.raise_for_status()
    return detect_and_embed(resp.content)
