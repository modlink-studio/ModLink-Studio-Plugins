from __future__ import annotations

import logging
import time
from types import ModuleType

import numpy as np

from modlink_sdk import FrameEnvelope, LoopDriver, SearchResult, StreamDescriptor

from .parser import ByteStreamParser, PalmMatrixAssembler

DEFAULT_DEVICE_ID = "palm_sensor.01"
DEFAULT_DISPLAY_NAME = "Palm Sensor"
DEFAULT_STREAM_DISPLAY_NAME = "Palm Sensor Field"
DEFAULT_STREAM_KEY = "pressure"
DEFAULT_SAMPLE_RATE_HZ = 10.0
DEFAULT_CHUNK_SIZE = 1
DEFAULT_CHANNEL_NAMES = ("pressure",)
SERIAL_PROVIDER = "serial"
SERIAL_BAUDRATE = 921_600
SERIAL_READ_LIMIT = 4096
# Set to True in code if you want the first complete 10x10 matrix after connect
# to be captured as the software zero reference.
ENABLE_ZERO_BASELINE = False

logger = logging.getLogger(__name__)


class PalmSensorDriver(LoopDriver):
    supported_providers = (SERIAL_PROVIDER,)
    loop_interval_ms = 5

    def __init__(self) -> None:
        super().__init__()
        self._serial: object | None = None
        self._parser = ByteStreamParser()
        self._assembler = PalmMatrixAssembler()
        self._seq = 0
        self._rate_estimator = _RateEstimator()
        self._zero_offset: np.ndarray | None = None

    @property
    def device_id(self) -> str:
        return DEFAULT_DEVICE_ID

    @property
    def display_name(self) -> str:
        return DEFAULT_DISPLAY_NAME

    def descriptors(self) -> list[StreamDescriptor]:
        return [
            StreamDescriptor(
                device_id=self.device_id,
                stream_key=DEFAULT_STREAM_KEY,
                payload_type="field",
                nominal_sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
                chunk_size=DEFAULT_CHUNK_SIZE,
                channel_names=DEFAULT_CHANNEL_NAMES,
                display_name=DEFAULT_STREAM_DISPLAY_NAME,
                metadata={"unit": "a.u.", "height": 10, "width": 10},
            )
        ]

    def search(self, provider: str) -> list[SearchResult]:
        if provider != SERIAL_PROVIDER:
            raise ValueError("Palm sensor provider must be 'serial'")

        list_ports = _require_list_ports()
        results: list[SearchResult] = []
        for port in list_ports.comports():
            device = str(getattr(port, "device", "") or "").strip()
            if not device:
                continue
            title = (
                str(getattr(port, "description", "") or "").strip()
                or str(getattr(port, "manufacturer", "") or "").strip()
                or device
            )
            subtitle_parts = ["Serial", device]
            serial_number = str(getattr(port, "serial_number", "") or "").strip()
            if serial_number:
                subtitle_parts.append(serial_number)
            results.append(
                SearchResult(
                    title=title,
                    subtitle=" | ".join(subtitle_parts),
                    extra={
                        "serial_port": device,
                        "baudrate": SERIAL_BAUDRATE,
                    },
                )
            )
        return results

    def connect_device(self, config: SearchResult) -> None:
        serial_module = _require_serial_module()
        self.disconnect_device()
        serial_port = str(config.extra["serial_port"])
        self._serial = serial_module.Serial(
            port=serial_port,
            baudrate=SERIAL_BAUDRATE,
            bytesize=serial_module.EIGHTBITS,
            parity=serial_module.PARITY_NONE,
            stopbits=serial_module.STOPBITS_ONE,
            timeout=0,
        )
        self._parser.reset()
        self._assembler.reset()
        self._rate_estimator.reset()
        self._seq = 0
        self._zero_offset = None

    def disconnect_device(self) -> None:
        self.stop_streaming()
        serial_port = self._serial
        self._serial = None
        self._parser.reset()
        self._assembler.reset()
        self._rate_estimator.reset()
        self._seq = 0
        self._zero_offset = None
        if serial_port is None:
            return
        close = getattr(serial_port, "close", None)
        if callable(close):
            close()

    def on_loop_started(self) -> None:
        if self._serial is None:
            raise RuntimeError("device is not connected")
        self._parser.reset()
        self._assembler.reset()
        self._rate_estimator.reset()
        self._seq = 0

    def on_loop_stopped(self) -> None:
        self._parser.reset()
        self._assembler.reset()
        self._rate_estimator.reset()
        self._seq = 0

    def loop(self) -> None:
        serial_port = self._serial
        if serial_port is None:
            return
        if not ENABLE_ZERO_BASELINE:
            self._zero_offset = None

        try:
            available = max(0, int(getattr(serial_port, "in_waiting", 0)))
            if available <= 0:
                return
            chunk = serial_port.read(min(available, SERIAL_READ_LIMIT))
        except Exception as exc:
            logger.exception("Palm sensor serial read failed")
            self._handle_connection_lost(
                code="PALM_SENSOR_READ_FAILED",
                message="Palm sensor serial read failed",
                detail=str(exc),
            )
            return

        if not chunk:
            return

        try:
            for frame in self._parser.feed(chunk):
                matrix = self._assembler.accept_frame(frame)
                if matrix is None:
                    continue
                matrix_data = np.ascontiguousarray(matrix, dtype=np.float32)
                if ENABLE_ZERO_BASELINE and self._zero_offset is None:
                    self._zero_offset = matrix_data.copy()
                if not ENABLE_ZERO_BASELINE:
                    self._zero_offset = None
                if ENABLE_ZERO_BASELINE and self._zero_offset is not None:
                    matrix_data = np.ascontiguousarray(matrix_data - self._zero_offset, dtype=np.float32)
                timestamp_ns = time.time_ns()
                self._rate_estimator.update(timestamp_ns)
                emitted = self.emit_frame(
                    FrameEnvelope(
                        device_id=self.device_id,
                        stream_key=DEFAULT_STREAM_KEY,
                        timestamp_ns=timestamp_ns,
                        data=matrix_data[np.newaxis, np.newaxis, :, :],
                        seq=self._seq,
                    )
                )
                if emitted:
                    self._seq += 1
        except Exception as exc:
            logger.exception("Palm sensor frame parsing failed")
            self._handle_connection_lost(
                code="PALM_SENSOR_PARSE_FAILED",
                message="Palm sensor frame parsing failed",
                detail=str(exc),
            )

    def _handle_connection_lost(self, *, code: str, message: str, detail: str) -> None:
        serial_port = self._serial
        self._serial = None
        self._parser.reset()
        self._assembler.reset()
        self._rate_estimator.reset()
        self._seq = 0
        self._zero_offset = None
        if serial_port is not None:
            close = getattr(serial_port, "close", None)
            if callable(close):
                close()
        self.emit_connection_lost({"code": code, "message": message, "detail": detail})


class _RateEstimator:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._last_timestamp_ns: int | None = None
        self._smoothed_rate_hz = 0.0

    def update(self, timestamp_ns: int) -> float:
        if self._last_timestamp_ns is None:
            self._last_timestamp_ns = int(timestamp_ns)
            return 0.0

        delta_ns = int(timestamp_ns) - self._last_timestamp_ns
        self._last_timestamp_ns = int(timestamp_ns)
        if delta_ns <= 0:
            return self._smoothed_rate_hz

        instantaneous = 1_000_000_000.0 / float(delta_ns)
        if self._smoothed_rate_hz <= 0.0:
            self._smoothed_rate_hz = instantaneous
        else:
            self._smoothed_rate_hz = (0.8 * self._smoothed_rate_hz) + (0.2 * instantaneous)
        return self._smoothed_rate_hz


def _require_serial_module() -> ModuleType:
    try:
        import serial
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Palm Sensor requires optional dependency 'pyserial'. "
            "Run `modlink-plugin install palm-sensor`."
        ) from exc
    return serial


def _require_list_ports() -> ModuleType:
    try:
        from serial.tools import list_ports
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Palm Sensor serial search requires optional dependency 'pyserial'. "
            "Run `modlink-plugin install palm-sensor`."
        ) from exc
    return list_ports
