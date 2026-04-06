from __future__ import annotations

import threading
import time
from types import ModuleType

import numpy as np

from modlink_sdk import Driver, FrameEnvelope, SearchResult, StreamDescriptor

DEFAULT_DEVICE_ID = "host_camera.01"
DEFAULT_FRAME_RATE_FPS = 30.0
DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480


class WebcamDriver(Driver):
    supported_providers = ("video",)

    def __init__(self) -> None:
        super().__init__()
        self._camera_index: int | None = None
        self._cap: object | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._seq = 0

    @property
    def device_id(self) -> str:
        return DEFAULT_DEVICE_ID

    @property
    def display_name(self) -> str:
        return "Host Camera"

    def descriptors(self) -> list[StreamDescriptor]:
        return [
            StreamDescriptor(
                device_id=self.device_id,
                modality="video",
                payload_type="video",
                nominal_sample_rate_hz=DEFAULT_FRAME_RATE_FPS,
                chunk_size=1,
                channel_names=("red", "green", "blue"),
                display_name="Host Camera RGB Stream",
                metadata={"width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT},
            )
        ]

    def search(self, provider: str) -> list[SearchResult]:
        if provider != "video":
            raise ValueError("Host camera driver provider must be 'video'")

        cv2 = _require_cv2()
        results: list[SearchResult] = []
        for index in range(10):
            # Try to open camera with default backend
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                backend_name = cap.getBackendName()
                cap.release()

                results.append(
                    SearchResult(
                        title=f"Camera {index}",
                        subtitle=f"{width}x{height} | {backend_name}",
                        extra={
                            "camera_index": index,
                            "width": width,
                            "height": height,
                        },
                    )
                )
            else:
                break

        return results

    def connect_device(self, config: SearchResult) -> None:
        self._camera_index = int(config.extra["camera_index"])
        self._seq = 0

    def disconnect_device(self) -> None:
        self.stop_streaming()
        self._camera_index = None
        self._seq = 0

    def start_streaming(self) -> None:
        if self._camera_index is None:
            raise RuntimeError("device is not connected")
        if self._running:
            return

        cv2 = _require_cv2()
        # Open camera with default backend (auto-detect best backend)
        self._cap = cv2.VideoCapture(self._camera_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Failed to open camera {self._camera_index}")

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_HEIGHT)
        self._cap.set(cv2.CAP_PROP_FPS, DEFAULT_FRAME_RATE_FPS)

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop_streaming(self) -> None:
        if not self._running:
            return

        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _capture_loop(self) -> None:
        cv2 = _require_cv2()
        while self._running and self._cap is not None:
            ret, frame = self._cap.read()
            if not ret:
                self.emit_connection_lost(
                    {
                        "code": "WEBCAM_READ_FAILED",
                        "message": "Failed to read frame from host camera",
                        "detail": "Camera connection lost or disconnected",
                    }
                )
                break
            if not self._running:
                break

            # Convert BGR to RGB (HWC format)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Normalize to 0-1 range and transpose to (channels, height, width)
            chw = (rgb_frame.astype(np.float32) / 255.0).transpose(2, 0, 1)

            # Format for VideoStreamView: (batch=3, time=1, height, width)
            # where batch dimension represents RGB channels
            data = np.ascontiguousarray(
                chw[:, np.newaxis, :, :],  # (3, 1, height, width)
                dtype=np.float32,
            )

            emitted = self.emit_frame(
                FrameEnvelope(
                    device_id=self.device_id,
                    modality="video",
                    timestamp_ns=time.time_ns(),
                    data=data,
                    seq=self._seq,
                )
            )
            if emitted:
                self._seq += 1

        self._running = False


def _require_cv2() -> ModuleType:
    try:
        import cv2
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Host Camera requires optional dependency 'opencv-python'. "
            "Run `modlink-plugin install host-camera`."
        ) from exc
    return cv2
