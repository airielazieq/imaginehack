"""ML training scripts and serialized model artifacts for Clover.

Models are trained offline via the ``train_*.py`` scripts in this package and
serialized (joblib) into ``backend/ml/models/``. The runtime detection /
forecasting modules load these artifacts and degrade to deterministic
fallbacks when an artifact is missing or unloadable.
"""
