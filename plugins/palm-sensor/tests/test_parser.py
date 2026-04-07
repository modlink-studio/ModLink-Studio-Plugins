from __future__ import annotations

import numpy as np

from palm_sensor.parser import (
    ByteStreamParser,
    FRAME_HEADER,
    LONG_FRAME_LENGTH,
    LONG_FRAME_TYPE,
    PalmMatrixAssembler,
    SHORT_FRAME_LENGTH,
    SHORT_FRAME_TYPE,
    parse_long_frame,
    parse_short_frame,
)


def _build_long_frame(rows: list[list[int]]) -> bytes:
    frame = bytearray(LONG_FRAME_LENGTH)
    frame[0:2] = FRAME_HEADER
    frame[4] = LONG_FRAME_TYPE
    for index, row in enumerate(rows):
        start = 12 + index * 16
        frame[start : start + 10] = bytes(row)
    return bytes(frame)


def _build_short_frame(rows: list[list[int]]) -> bytes:
    frame = bytearray(SHORT_FRAME_LENGTH)
    frame[0:2] = FRAME_HEADER
    frame[4] = SHORT_FRAME_TYPE
    for index, row in enumerate(rows):
        start = 12 + index * 16
        frame[start : start + 10] = bytes(row)
    return bytes(frame)


def _expected_row(start: int) -> list[int]:
    raw = list(range(start, start + 10))
    return [raw[index] for index in (9, 8, 7, 6, 5, 0, 1, 2, 3, 4)]


def test_parser_discards_garbage_and_recovers_split_header() -> None:
    parser = ByteStreamParser()
    long_frame = _build_long_frame([list(range(index * 10, index * 10 + 10)) for index in range(8)])

    first = parser.feed(b"\x00\x01\x02\xaa")
    second = parser.feed(b"\x55" + long_frame[2:50])
    third = parser.feed(long_frame[50:])

    assert first == []
    assert second == []
    assert third == [long_frame]


def test_parser_skips_invalid_frame_type_and_finds_next_valid_frame() -> None:
    parser = ByteStreamParser()
    invalid = bytearray(32)
    invalid[0:2] = FRAME_HEADER
    invalid[4] = 0x77
    short_frame = _build_short_frame([list(range(10, 20)), list(range(20, 30))])

    frames = parser.feed(bytes(invalid) + short_frame)

    assert frames == [short_frame]


def test_parse_long_frame_reorders_columns() -> None:
    rows = [list(range(index * 10, index * 10 + 10)) for index in range(8)]

    parsed = parse_long_frame(_build_long_frame(rows))

    assert parsed.shape == (8, 10)
    assert parsed.dtype == np.uint8
    assert parsed.tolist()[0] == _expected_row(0)
    assert parsed.tolist()[7] == _expected_row(70)


def test_parse_short_frame_reorders_columns() -> None:
    rows = [list(range(80, 90)), list(range(90, 100))]

    parsed = parse_short_frame(_build_short_frame(rows))

    assert parsed.shape == (2, 10)
    assert parsed.tolist()[0] == _expected_row(80)
    assert parsed.tolist()[1] == _expected_row(90)


def test_assembler_waits_for_both_frame_types_and_uses_latest_long_frame() -> None:
    assembler = PalmMatrixAssembler()
    long_rows_v1 = [list(range(index * 10, index * 10 + 10)) for index in range(8)]
    long_rows_v2 = [list(range(100 + index * 10, 110 + index * 10)) for index in range(8)]
    short_rows = [list(range(200, 210)), list(range(210, 220))]

    assert assembler.accept_frame(_build_long_frame(long_rows_v1)) is None
    assert assembler.accept_frame(_build_long_frame(long_rows_v2)) is None
    matrix = assembler.accept_frame(_build_short_frame(short_rows))

    assert matrix is not None
    assert matrix.shape == (10, 10)
    assert matrix.tolist()[0] == _expected_row(100)
    assert matrix.tolist()[7] == _expected_row(170)
    assert matrix.tolist()[8] == _expected_row(200)
    assert matrix.tolist()[9] == _expected_row(210)


def test_assembler_does_not_reemit_without_both_updates() -> None:
    assembler = PalmMatrixAssembler()
    long_rows = [list(range(index * 10, index * 10 + 10)) for index in range(8)]
    short_rows = [list(range(80, 90)), list(range(90, 100))]

    assert assembler.accept_frame(_build_long_frame(long_rows)) is None
    assert assembler.accept_frame(_build_short_frame(short_rows)) is not None
    assert assembler.accept_frame(_build_short_frame(short_rows)) is None
