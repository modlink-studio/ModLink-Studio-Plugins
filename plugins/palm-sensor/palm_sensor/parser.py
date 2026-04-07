from __future__ import annotations

import numpy as np

FRAME_HEADER = b"\xAA\x55"
FRAME_TYPE_OFFSET = 4
FRAME_PREFIX_LENGTH = 6
SHORT_FRAME_TYPE = 0x01
LONG_FRAME_TYPE = 0x02
SHORT_FRAME_LENGTH = 134
LONG_FRAME_LENGTH = 150
LONG_FRAME_TRAILER_LENGTH = 16
ROW_SLICES: tuple[tuple[int, int], ...] = (
    (6, 16),
    (22, 32),
    (38, 48),
    (54, 64),
    (70, 80),
    (86, 96),
    (102, 112),
    (118, 128),
)
COLUMN_REORDER = np.asarray([9, 8, 7, 6, 5, 0, 1, 2, 3, 4], dtype=np.intp)


class ByteStreamParser:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes | bytearray | memoryview) -> list[bytes]:
        if data:
            self._buffer.extend(data)

        frames: list[bytes] = []
        while True:
            header_index = self._buffer.find(FRAME_HEADER)
            if header_index < 0:
                self._retain_possible_header_prefix()
                break
            if header_index > 0:
                del self._buffer[:header_index]
            if len(self._buffer) <= FRAME_TYPE_OFFSET:
                break

            frame_length = frame_length_for_type(self._buffer[FRAME_TYPE_OFFSET])
            if frame_length is None:
                del self._buffer[0]
                continue
            if len(self._buffer) < frame_length:
                break

            frames.append(bytes(self._buffer[:frame_length]))
            del self._buffer[:frame_length]

        return frames

    def _retain_possible_header_prefix(self) -> None:
        if self._buffer[-1:] == FRAME_HEADER[:1]:
            self._buffer[:] = FRAME_HEADER[:1]
            return
        self._buffer.clear()


class PalmMatrixAssembler:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._long_rows: np.ndarray | None = None
        self._short_rows: np.ndarray | None = None
        self._long_updated = False
        self._short_updated = False

    def accept_frame(self, frame: bytes) -> np.ndarray | None:
        frame_type = frame_type_of(frame)
        if frame_type == LONG_FRAME_TYPE:
            self._long_rows = parse_long_frame(frame)
            self._long_updated = True
        elif frame_type == SHORT_FRAME_TYPE:
            self._short_rows = parse_short_frame(frame)
            self._short_updated = True
        else:
            raise ValueError(f"unsupported frame type: {frame_type!r}")

        if not (self._long_updated and self._short_updated):
            return None
        if self._long_rows is None or self._short_rows is None:
            return None

        matrix = np.vstack((self._long_rows, self._short_rows)).astype(np.uint8, copy=False)
        self._long_updated = False
        self._short_updated = False
        return matrix


def frame_type_of(frame: bytes | bytearray | memoryview) -> int:
    if len(frame) <= FRAME_TYPE_OFFSET:
        raise ValueError("frame is too short to contain a type byte")
    return int(frame[FRAME_TYPE_OFFSET])


def frame_length_for_type(frame_type: int) -> int | None:
    if frame_type == SHORT_FRAME_TYPE:
        return SHORT_FRAME_LENGTH
    if frame_type == LONG_FRAME_TYPE:
        return LONG_FRAME_LENGTH
    return None


def parse_long_frame(frame: bytes | bytearray | memoryview) -> np.ndarray:
    _validate_frame(frame, LONG_FRAME_TYPE, LONG_FRAME_LENGTH)
    payload = bytes(frame)[FRAME_PREFIX_LENGTH : LONG_FRAME_LENGTH - LONG_FRAME_TRAILER_LENGTH]
    return _extract_rows(payload, ROW_SLICES)


def parse_short_frame(frame: bytes | bytearray | memoryview) -> np.ndarray:
    _validate_frame(frame, SHORT_FRAME_TYPE, SHORT_FRAME_LENGTH)
    payload = bytes(frame)[FRAME_PREFIX_LENGTH:]
    return _extract_rows(payload, ROW_SLICES[:2])


def _validate_frame(frame: bytes | bytearray | memoryview, expected_type: int, expected_length: int) -> None:
    actual_length = len(frame)
    if actual_length != expected_length:
        raise ValueError(f"expected frame length {expected_length}, got {actual_length}")
    if frame[:2] != FRAME_HEADER:
        raise ValueError("frame header mismatch")
    actual_type = frame_type_of(frame)
    if actual_type != expected_type:
        raise ValueError(f"expected frame type {expected_type:#04x}, got {actual_type:#04x}")


def _extract_rows(payload: bytes, row_slices: tuple[tuple[int, int], ...]) -> np.ndarray:
    rows = [payload[start:stop] for start, stop in row_slices]
    if any(len(row) != 10 for row in rows):
        raise ValueError("payload does not contain enough bytes for row extraction")
    raw = np.asarray([list(row) for row in rows], dtype=np.uint8)
    return np.ascontiguousarray(raw[:, COLUMN_REORDER], dtype=np.uint8)
