"""Live webcam capture for `faceid.run --webcam`.

Opens the default camera, draws a live YuNet bounding box per frame (via
`face.detect_faces`, which skips the expensive SFace embedding step -- that
only needs to run once, on the frame actually captured), and on Enter/Space
runs the real `face.detect_and_embed` on that frame before saving it to disk.

Kept separate from `faceid/run.py` so a missing camera / cancelled capture
can be handled as a clean, isolated failure that doesn't touch Steps 1-5.
"""
from __future__ import annotations

import pathlib
import sys

import cv2

from . import console as console_mod
from . import face

WINDOW_NAME = "faceid webcam capture -- Enter/Space: capture, Esc: cancel"


def _log(msg: str) -> None:
    console_mod.log(msg, prefix="webcam")


def capture_frame(dest_path: pathlib.Path) -> pathlib.Path | None:
    """Show a live preview with a face bounding box; on Enter/Space, verify a
    face is detectable in that exact frame, save it to `dest_path`, and
    return the path. Returns None if the user cancels (Esc) or the camera
    can't be opened.
    """
    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    cap = cv2.VideoCapture(0, backend)
    if not cap.isOpened():
        _log("ERROR: could not open webcam (device 0).")
        cap.release()
        return None

    _log("press Enter or Space to capture, Esc to cancel")
    consecutive_bad_reads = 0
    max_consecutive_bad_reads = 10
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                consecutive_bad_reads += 1
                if consecutive_bad_reads >= max_consecutive_bad_reads:
                    _log(f"ERROR: failed to read a frame from the webcam "
                         f"({max_consecutive_bad_reads} consecutive failures).")
                    return None
                continue
            consecutive_bad_reads = 0

            preview = frame.copy()
            faces = face.detect_faces(frame)
            if faces is not None:
                for f in faces:
                    x, y, w, h = f[:4].astype(int)
                    cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 255, 0), 2)

            cv2.imshow(WINDOW_NAME, preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (13, 32):  # Enter, Space
                result = face.detect_and_embed(frame)
                if result is None:
                    _log("no face detected in this frame -- keep trying")
                    continue
                cv2.imwrite(str(dest_path), frame)
                _log(f"captured -> {dest_path} (detect_score={result.detect_score:.3f})")
                return dest_path
            if key == 27:  # Esc
                _log("capture cancelled")
                return None
    finally:
        cap.release()
        try:
            cv2.destroyWindow(WINDOW_NAME)
        except cv2.error:
            pass  # window was never shown (e.g. failed on the first frame read)
