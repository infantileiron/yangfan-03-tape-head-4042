"""Singular-module alias for :mod:`src.business.baselines`."""

from src.business.baselines import *  # noqa: F401,F403
from src.business import baselines as _rules

# Re-export explicitly for static analyzers and ``from src.business.baseline import ...``.
globals().update({name: getattr(_rules, name) for name in getattr(_rules, "__all__", [])})
