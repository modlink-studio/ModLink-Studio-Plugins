from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterable
from types import ModuleType

import numpy as np

from modlink_sdk import FrameEnvelope, LoopDriver, SearchResult, StreamDescriptor

DEFAULT_GANGLION_DEVICE_ID = "openbci_ganglion.01"
DEFAULT_GANGLION_DISPLAY_NAME = "OpenBCI Ganglion"
DEFAULT_SAMPLE_RATE_HZ = 200.0
DEFAULT_CHUNK_SIZE = 10
DEFAULT_CHANNEL_NAMES = ("ch1", "ch2", "ch3", "ch4")
_LIKELY_GANGLION_TOKENS = ("ganglion", "openbci")
_LIKELY_DONGLE_TOKENS = ("ganglion", "openbci", "bled112", "silicon labs", "cp210")

logger = logging.getLogger(__name__)


class OpenBCIGanglionDriver(LoopDriver):
    supported_providers = ("ble", "serial")
    loop_interval_ms = int(round(1000 * DEFAULT_CHUNK_SIZE / DEFAULT_SAMPLE_RATE_HZ))

    def __init__(self) -> None:
        super().__init__()
        self._board = None
        self._transport = ""
        self._eeg_channels: tuple[int, ...] = ()
        self._buffer = np.empty((len(DEFAULT_CHANNEL_NAMES), 0), dtype=np.float32)
        self._seq = 0

    @property
    def device_id(self) -> str:
        return DEFAULT_GANGLION_DEVICE_ID

    @property
    def display_name(self) -> str:
        return DEFAULT_GANGLION_DISPLAY_NAME

    def descriptors(self) -> list[StreamDescriptor]:
        return [
            StreamDescriptor(
                device_id=self.device_id,
                modality="eeg",
                payload_type="signal",
                nominal_sample_rate_hz=DEFAULT_SAMPLE_RATE_HZ,
                chunk_size=DEFAULT_CHUNK_SIZE,
                channel_names=DEFAULT_CHANNEL_NAMES,
                display_name="Ganglion EEG",
                metadata={"unit": "uV"},
            )
        ]

    def search(self, provider: str) -> list[SearchResult]:
        if provider == "ble":
            bleak_scanner = _require_bleak_scanner()
            devices = asyncio.run(bleak_scanner.discover(timeout=5.0))
            results = [
                SearchResult(
                    title=(device.name or "BLE device").strip() or "BLE device",
                    subtitle=f"Native BLE | {device.address}",
                    extra={
                        "transport": "native_ble",
                        "serial_number": (device.name or "").strip(),
                        "address": device.address,
                    },
                )
                for device in devices
                if device.address
            ]
            return _preferred_results(results, transport="native_ble")

        if provider == "serial":
            list_ports = _require_list_ports()
            results = [
                SearchResult(
                    title=_port_title(port),
                    subtitle=(
                        f"Dongle | {port.device} | {port.serial_number}"
                        if port.serial_number
                        else f"Dongle | {port.device}"
                    ),
                    extra={
                        "transport": "dongle",
                        "serial_port": port.device,
                        "serial_number": str(port.serial_number or "").strip(),
                    },
                )
                for port in list_ports.comports()
                if port.device
            ]
            return _preferred_results(results, transport="dongle")

        raise ValueError("OpenBCI Ganglion search provider must be 'ble' or 'serial'")

    def connect_device(self, config: SearchResult) -> None:
        board_ids, board_shim, brain_flow_input_params = _require_brainflow()
        extra = config.extra
        params = brain_flow_input_params()
        params.timeout = 15
        params.other_info = "fw:auto"

        if extra["transport"] == "dongle":
            params.serial_port = extra["serial_port"]
            board_id = int(board_ids.GANGLION_BOARD.value)
        else:
            params.serial_number = extra["serial_number"]
            board_id = int(board_ids.GANGLION_NATIVE_BOARD.value)

        board = board_shim(board_id, params)
        board.prepare_session()

        self._board = board
        self._transport = extra["transport"]
        self._eeg_channels = tuple(board_shim.get_eeg_channels(board_id))
        self._buffer = np.empty((len(DEFAULT_CHANNEL_NAMES), 0), dtype=np.float32)
        self._seq = 0

    def disconnect_device(self) -> None:
        self.stop_streaming()
        if self._board is None:
            return

        if self._transport == "dongle":
            try:
                self._board.config_board("v")
            except Exception:
                logger.exception("OpenBCI Ganglion dongle cleanup command failed during disconnect")
                pass

        try:
            self._board.release_session()
        finally:
            self._board = None
            self._transport = ""
            self._eeg_channels = ()
            self._buffer = np.empty((len(DEFAULT_CHANNEL_NAMES), 0), dtype=np.float32)
            self._seq = 0

    def on_loop_started(self) -> None:
        if self._board is None:
            raise RuntimeError("device is not connected")

        self._board.start_stream(45_000, "")
        self._buffer = np.empty((len(DEFAULT_CHANNEL_NAMES), 0), dtype=np.float32)
        self._seq = 0

    def on_loop_stopped(self) -> None:
        try:
            if self._board is not None:
                self._board.stop_stream()
        finally:
            self._buffer = np.empty((len(DEFAULT_CHANNEL_NAMES), 0), dtype=np.float32)
            self._seq = 0

    def loop(self) -> None:
        if self._board is None:
            return
        if self._board.get_board_data_count() <= 0:
            return

        try:
            board_data = self._board.get_board_data()
            eeg_data = np.ascontiguousarray(
                board_data[list(self._eeg_channels), :],
                dtype=np.float32,
            )
        except Exception as exc:
            logger.exception("OpenBCI Ganglion stream polling failed")
            self.disconnect_device()
            self.emit_connection_lost(
                {
                    "code": "GANGLION_STREAM_FAILED",
                    "message": "OpenBCI Ganglion stream polling failed",
                    "detail": str(exc),
                }
            )
            return

        if eeg_data.size == 0:
            return

        self._buffer = np.ascontiguousarray(
            np.concatenate((self._buffer, eeg_data), axis=1),
            dtype=np.float32,
        )
        while self._buffer.shape[1] >= DEFAULT_CHUNK_SIZE:
            chunk = np.ascontiguousarray(
                self._buffer[:, :DEFAULT_CHUNK_SIZE],
                dtype=np.float32,
            )
            self._buffer = np.ascontiguousarray(
                self._buffer[:, DEFAULT_CHUNK_SIZE:],
                dtype=np.float32,
            )
            emitted = self.emit_frame(
                FrameEnvelope(
                    device_id=self.device_id,
                    modality="eeg",
                    timestamp_ns=time.time_ns(),
                    data=chunk,
                    seq=self._seq,
                )
            )
            if emitted:
                self._seq += 1


def _preferred_results(
    results: Iterable[SearchResult],
    *,
    transport: str,
) -> list[SearchResult]:
    unique: list[SearchResult] = []
    seen: set[tuple[str, str]] = set()

    for result in results:
        extra = result.extra
        key = (
            transport,
            str(extra.get("address") or extra.get("serial_port") or "").strip().lower(),
        )
        if not key[1] or key in seen:
            continue
        seen.add(key)
        unique.append(result)

    tokens = _LIKELY_GANGLION_TOKENS if transport == "native_ble" else _LIKELY_DONGLE_TOKENS
    preferred = [
        result
        for result in unique
        if _contains_any_token(
            (
                result.title,
                result.subtitle,
                str(result.extra.get("serial_number", "")),
            ),
            tokens,
        )
    ]
    ordered = preferred or unique
    return sorted(ordered, key=lambda item: (item.title.lower(), item.subtitle.lower()))


def _contains_any_token(parts: Iterable[str], tokens: Iterable[str]) -> bool:
    haystack = " ".join(str(part).strip().lower() for part in parts if str(part).strip())
    return any(token in haystack for token in tokens)


def _port_title(port: object) -> str:
    description = str(getattr(port, "description", "") or "").strip()
    manufacturer = str(getattr(port, "manufacturer", "") or "").strip()
    device = str(getattr(port, "device", "") or "").strip()
    for candidate in (description, manufacturer, device):
        if candidate:
            return candidate
    return "Serial device"


def _require_bleak_scanner() -> object:
    try:
        from bleak import BleakScanner
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "OpenBCI Ganglion BLE search requires optional dependency 'bleak'. "
            "Run `modlink-plugin install openbci-ganglion`."
        ) from exc
    return BleakScanner


def _require_list_ports() -> ModuleType:
    try:
        from serial.tools import list_ports
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "OpenBCI Ganglion serial search requires optional dependency 'pyserial'. "
            "Run `modlink-plugin install openbci-ganglion`."
        ) from exc
    return list_ports


def _require_brainflow() -> tuple[object, object, object]:
    try:
        from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "OpenBCI Ganglion requires optional dependency 'brainflow'. "
            "Run `modlink-plugin install openbci-ganglion`."
        ) from exc
    return BoardIds, BoardShim, BrainFlowInputParams
