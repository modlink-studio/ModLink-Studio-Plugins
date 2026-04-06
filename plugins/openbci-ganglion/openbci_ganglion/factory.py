from __future__ import annotations


def create_driver():
    from .driver import OpenBCIGanglionDriver
    """Factory used by the ``modlink.drivers`` entry point."""

    return OpenBCIGanglionDriver()
