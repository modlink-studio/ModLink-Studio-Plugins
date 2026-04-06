from __future__ import annotations

import logging
import time
from types import ModuleType

import numpy as np

from modlink_sdk import Driver, FrameEnvelope, SearchResult, StreamDescriptor

DEFAULT_DEVICE_ID = "host_microphone.01"
DEFAULT_SAMPLE_RATE_HZ = 16_000.0
DEFAULT_CHUNK_SIZE = 1024

logger = logging.getLogger(__name__)


class MicrophoneDemoDriver(Driver):
    supported_providers = ("audio",)

    def __init__(self) -> None:
        super().__init__()
        self._device_index: int | None = None
        self._stream: object | None = None
        self._callbacks_enabled = False
        self._seq = 0

    @property
    def device_id(self) -> str:
        return DEFAULT_DEVICE_ID

    @property
    def display_name(self) -> str:
        return "Host Microphone"

    def descriptors(self) -> list[StreamDescriptor]:
        return [
            StreamDescriptor(
                device_id=self.device_id,
                modality="audio",
                payload_type="signal",
                nominal_sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
                chunk_size=DEFAULT_CHUNK_SIZE,
                channel_names=("mic",),
                display_name="Host Microphone Waveform",
            )
        ]

    def search(self, provider: str) -> list[SearchResult]:
        if provider != "audio":
            raise ValueError("Host microphone provider must be 'audio'")

        sd = _require_sounddevice()
        return [
            SearchResult(
                title=device["name"],
                subtitle=f"index={index}",
                extra={"device_index": index},
            )
            for index, device in enumerate(sd.query_devices())
            if device["max_input_channels"] > 0
        ]

    def connect_device(self, config: SearchResult) -> None:
        self._device_index = int(config.extra["device_index"])
        self._seq = 0

    def disconnect_device(self) -> None:
        self.stop_streaming()
        self._device_index = None
        self._seq = 0

    def start_streaming(self) -> None:
        if self._device_index is None:
            raise RuntimeError("device is not connected")
        if self._stream is not None:
            return

        sd = _require_sounddevice()
        stream = sd.InputStream(
            device=self._device_index,
            channels=1,
            samplerate=DEFAULT_SAMPLE_RATE_HZ,
            blocksize=DEFAULT_CHUNK_SIZE,
            callback=self._on_audio,
        )
        try:
            stream.start()
        except Exception:
            logger.exception("Host microphone stream failed to start")
            stream.close()
            raise

        self._stream = stream
        self._callbacks_enabled = True

    def stop_streaming(self) -> None:
        stream = self._stream
        self._callbacks_enabled = False
        if stream is None:
            return
        try:
            stream.stop()
        finally:
            stream.close()
            self._stream = None

    def _on_audio(
        self,
        indata: np.ndarray,
        frames: int,
        timestamp: object,
        status: object,
    ) -> None:
        if not self._callbacks_enabled:
            return
        if status:
            logger.warning("Host microphone callback reported status: %s", status)

        emitted = self.emit_frame(
            FrameEnvelope(
                device_id=self.device_id,
                modality="audio",
                timestamp_ns=time.time_ns(),
                data=np.ascontiguousarray(indata[:, 0], dtype=np.float32)[np.newaxis, :],
                seq=self._seq,
            )
        )
        if emitted:
            self._seq += 1


def _require_sounddevice() -> ModuleType:
    try:
        import sounddevice as sd
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Host Microphone requires optional dependency 'sounddevice'. "
            "Run `modlink-plugin install host-microphone`."
        ) from exc
    return sd
