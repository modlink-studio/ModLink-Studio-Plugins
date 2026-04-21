from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from modlink_sdk import SearchResult

from palm_sensor.driver import PalmSensorDriver


def _build_long_frame(rows: list[list[int]]) -> bytes:
    frame = bytearray(150)
    frame[0:2] = b"\xAA\x55"
    frame[4] = 0x02
    for index, row in enumerate(rows):
        start = 12 + index * 16
        frame[start : start + 10] = bytes(row)
    return bytes(frame)


def _build_short_frame(rows: list[list[int]]) -> bytes:
    frame = bytearray(134)
    frame[0:2] = b"\xAA\x55"
    frame[4] = 0x01
    for index, row in enumerate(rows):
        start = 12 + index * 16
        frame[start : start + 10] = bytes(row)
    return bytes(frame)


def _expected_row(start: int) -> list[int]:
    raw = list(range(start, start + 10))
    return [raw[index] for index in (9, 8, 7, 6, 5, 0, 1, 2, 3, 4)]


@dataclass
class _FakePort:
    device: str
    description: str
    serial_number: str = ""
    manufacturer: str = ""


class _FakeListPorts:
    def __init__(self, ports: list[_FakePort]) -> None:
        self._ports = ports

    def comports(self) -> list[_FakePort]:
        return list(self._ports)


class _FakeSerialPort:
    def __init__(self, payload: bytes = b"", *, fail_on_read: bool = False, port: str = "COM7") -> None:
        self._buffer = bytearray(payload)
        self.fail_on_read = fail_on_read
        self.port = port
        self.closed = False

    @property
    def in_waiting(self) -> int:
        return len(self._buffer)

    def read(self, size: int) -> bytes:
        if self.fail_on_read:
            raise OSError("read failed")
        chunk = bytes(self._buffer[:size])
        del self._buffer[:size]
        return chunk

    def close(self) -> None:
        self.closed = True


class _FakeSerialModule:
    EIGHTBITS = 8
    PARITY_NONE = "N"
    STOPBITS_ONE = 1

    def __init__(self, port: _FakeSerialPort) -> None:
        self._port = port
        self.calls: list[dict[str, object]] = []

    def Serial(self, **kwargs: object) -> _FakeSerialPort:
        self.calls.append(dict(kwargs))
        self._port.port = str(kwargs["port"])
        return self._port


def test_descriptors_match_field_contract() -> None:
    driver = PalmSensorDriver()

    descriptor = driver.descriptors()[0]

    assert descriptor.device_id == "palm_sensor.01"
    assert descriptor.stream_key == "pressure"
    assert descriptor.payload_type == "field"
    assert descriptor.chunk_size == 1
    assert descriptor.channel_names == ("pressure",)
    assert descriptor.metadata == {"unit": "a.u.", "height": 10, "width": 10}


def test_search_returns_serial_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = PalmSensorDriver()
    fake_ports = _FakeListPorts([_FakePort(device="COM7", description="Palm Sensor Bridge", serial_number="ABC123")])
    monkeypatch.setattr("palm_sensor.driver._require_list_ports", lambda: fake_ports)

    results = driver.search("serial")

    assert results == [
        SearchResult(
            title="Palm Sensor Bridge",
            subtitle="Serial | COM7 | ABC123",
            extra={"serial_port": "COM7", "baudrate": 921_600},
        )
    ]


def test_loop_emits_complete_field_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    long_rows = [list(range(index * 10, index * 10 + 10)) for index in range(8)]
    short_rows = [list(range(80, 90)), list(range(90, 100))]
    payload = _build_long_frame(long_rows) + _build_short_frame(short_rows)
    fake_port = _FakeSerialPort(payload=payload)
    fake_serial_module = _FakeSerialModule(fake_port)
    emitted_frames: list[object] = []

    monkeypatch.setattr("palm_sensor.driver._require_serial_module", lambda: fake_serial_module)
    monkeypatch.setattr("palm_sensor.driver.time.time_ns", lambda: 1_000_000_000)

    driver = PalmSensorDriver()
    monkeypatch.setattr(driver, "emit_frame", lambda frame: emitted_frames.append(frame) or True)

    driver.connect_device(SearchResult(title="Palm", extra={"serial_port": "COM7"}))
    driver.on_loop_started()
    driver.loop()

    assert len(emitted_frames) == 1
    frame = emitted_frames[0]
    assert frame.device_id == "palm_sensor.01"
    assert frame.stream_key == "pressure"
    assert frame.seq == 0
    assert frame.data.shape == (1, 1, 10, 10)
    assert frame.data.dtype == np.float32
    assert frame.data[0, 0, 0, :].tolist() == _expected_row(0)
    assert frame.data[0, 0, 9, :].tolist() == _expected_row(90)


def test_loop_emits_connection_lost_on_serial_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_port = _FakeSerialPort(fail_on_read=True)
    fake_serial_module = _FakeSerialModule(fake_port)
    connection_lost: list[dict[str, object]] = []

    monkeypatch.setattr("palm_sensor.driver._require_serial_module", lambda: fake_serial_module)

    driver = PalmSensorDriver()
    monkeypatch.setattr(driver, "emit_connection_lost", lambda payload: connection_lost.append(payload))

    driver.connect_device(SearchResult(title="Palm", extra={"serial_port": "COM7"}))
    driver.on_loop_started()
    fake_port._buffer.extend(b"\x00")
    driver.loop()

    assert connection_lost
    assert connection_lost[0]["code"] == "PALM_SENSOR_READ_FAILED"
    assert fake_port.closed is True


def test_zero_baseline_uses_first_complete_matrix_as_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    long_rows_a = [list(range(index * 10, index * 10 + 10)) for index in range(8)]
    short_rows_a = [list(range(80, 90)), list(range(90, 100))]
    long_rows_b = [list(range(10 + index * 10, 20 + index * 10)) for index in range(8)]
    short_rows_b = [list(range(90, 100)), list(range(100, 110))]
    payload = (
        _build_long_frame(long_rows_a)
        + _build_short_frame(short_rows_a)
        + _build_long_frame(long_rows_b)
        + _build_short_frame(short_rows_b)
    )
    fake_port = _FakeSerialPort(payload=payload)
    fake_serial_module = _FakeSerialModule(fake_port)
    emitted_frames: list[object] = []

    monkeypatch.setattr("palm_sensor.driver._require_serial_module", lambda: fake_serial_module)
    monkeypatch.setattr("palm_sensor.driver.time.time_ns", lambda: 1_000_000_000)
    monkeypatch.setattr("palm_sensor.driver.ENABLE_ZERO_BASELINE", True)

    driver = PalmSensorDriver()
    monkeypatch.setattr(driver, "emit_frame", lambda frame: emitted_frames.append(frame) or True)

    driver.connect_device(SearchResult(title="Palm", extra={"serial_port": "COM7"}))
    driver.on_loop_started()
    driver.loop()

    assert len(emitted_frames) == 2
    first = emitted_frames[0]
    second = emitted_frames[1]
    assert np.allclose(first.data, 0.0)
    assert second.data[0, 0, 0, :].tolist() == [10.0] * 10
    assert second.data[0, 0, 9, :].tolist() == [10.0] * 10


def test_disabled_zero_baseline_clears_existing_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    driver = PalmSensorDriver()
    monkeypatch.setattr("palm_sensor.driver.ENABLE_ZERO_BASELINE", False)
    driver._zero_offset = np.ones((10, 10), dtype=np.float32)
    fake_port = _FakeSerialPort(payload=_build_long_frame([list(range(index * 10, index * 10 + 10)) for index in range(8)]))
    driver._serial = fake_port
    driver.loop()

    assert driver._zero_offset is None
