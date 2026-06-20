"""Shared utilities for the AI / Mock Data subteam: paths, feature definitions,
encoders, and data loaders. Imported by the mock generator, ML training, and
the detection/forecast inference modules.

IMPORTANT (Windows): scikit-learn and xgboost ship separate OpenMP runtimes;
loading both in one process can deadlock or abort. We set these guards here,
before any ML library is imported, because ml.common is imported first by every
module in this package. Keep this import at the top of the dependency chain.
"""
import os as _os

_os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
_os.environ.setdefault("OMP_NUM_THREADS", "1")
