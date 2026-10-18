"""Compatibility layer for finding lifecycle utilities."""
from src.lifecycle import *
from src.lifecycle_manager import LifecycleManager

__all__ = [
    "LifecycleManager",
    "STATE_MARKER",
    "encode_state",
    "decode_state",
    "decode_state_from_text",
    "finding_key",
    "parse_unified_patch",
    "is_line_in_patch",
]
