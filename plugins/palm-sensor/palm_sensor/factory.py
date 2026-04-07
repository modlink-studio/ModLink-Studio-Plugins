from __future__ import annotations

from .driver import PalmSensorDriver


def create_driver() -> PalmSensorDriver:
    return PalmSensorDriver()
