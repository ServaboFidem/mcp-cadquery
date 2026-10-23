"""Stub of the top-level ``cadquery`` package for tests.

The shim's startup check does ``import cadquery`` and exits non-zero when it
fails. This stub lets the stdio subprocess test exercise the real startup
path (successful import) with no OCC install; the missing-OCC test uses an
override dir without this file.
"""

__version__ = "0.0.0-fake"
