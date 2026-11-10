"""YuNet detection and SFace recognition on OpenCV (CPU, in a worker thread)."""

import asyncio
import threading
from pathlib import Path
from typing import Any

from app.modules.faces.domain.errors import MultipleFacesError

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
SFACE_FILE = "face_recognition_sface_2021dec.onnx"
MAX_SIDE = 1600  # larger photos are scaled down before detection
SCORE_THRESHOLD = 0.8


class OpenCvFaceEngine:
    """Finds the one face of a photo and returns its SFace embedding."""

    def __init__(self, model_dir: Path) -> None:
        """Remember the model folder; the models load on first use."""
        self._yunet = model_dir / YUNET_FILE
        self._sface = model_dir / SFACE_FILE
        self._lock = threading.Lock()
        self._detector: Any = None
        self._recognizer: Any = None

    async def embed(self, image: bytes) -> list[float] | None:
        """Return the embedding, None without a face; several faces raise."""
        return await asyncio.to_thread(self._embed, image)

    def _load(self) -> None:
        import cv2

        for path in (self._yunet, self._sface):
            if not path.is_file():
                raise FileNotFoundError(f"face model missing: {path}")
        self._detector = cv2.FaceDetectorYN.create(
            str(self._yunet), "", (320, 320), SCORE_THRESHOLD
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(self._sface), "")

    def _embed(self, image: bytes) -> list[float] | None:
        import cv2
        import numpy as np

        with self._lock:  # the OpenCV models keep state between calls
            if self._detector is None:
                self._load()
            frame = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return None
            height, width = frame.shape[:2]
            scale = min(1.0, MAX_SIDE / max(height, width))
            if scale < 1.0:
                frame = cv2.resize(frame, (int(width * scale), int(height * scale)))
                height, width = frame.shape[:2]
            self._detector.setInputSize((width, height))
            _, faces = self._detector.detect(frame)
            if faces is None or len(faces) == 0:
                return None
            if len(faces) > 1:
                raise MultipleFacesError()
            aligned = self._recognizer.alignCrop(frame, faces[0])
            feature = self._recognizer.feature(aligned)
            return [float(x) for x in feature.flatten()]
