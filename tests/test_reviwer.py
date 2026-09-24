import pytest

from src.reviewer import build_model


def test_reviewer_module_imports():
    assert callable(build_model)
