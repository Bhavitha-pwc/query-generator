"""Shared color palette for the dashboard (fixed, never themed) — from the
dataviz skill reference palette. Single source so nl2sql and codegen panels
render status consistently.
"""
COLOR_GOOD = "#0ca30c"
COLOR_CRITICAL = "#d03b3b"
COLOR_MUTED = "#898781"
COLOR_WARNING = "#fab219"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"

CONFIDENCE_COLOR = {"high": COLOR_GOOD, "medium": COLOR_WARNING, "low": COLOR_CRITICAL}
