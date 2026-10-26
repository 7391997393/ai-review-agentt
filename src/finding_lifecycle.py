"""Compatibility layer for lifecycle operations."""
from src.lifecycle import *
from src.lifecycle_manager import LifecycleManager

__all__ = ["LifecycleManager", "encode_state", "decode_state", "finding_key"]
