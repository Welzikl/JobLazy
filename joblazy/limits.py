"""Default local daily allowances shared by search and terminal workflows."""

DAILY_JOBS = 25
DAILY_REQUESTS = 50


def account_model(data, store, model_name):
    """Reserve every uncached call, including calls made during form resume."""
    from datetime import datetime, timezone
    from pathlib import Path
    from .model import CodexModel
    return CodexModel(Path(data) / 'model-cache', model_name,
                      before_request=lambda: store.reserve_model_request(
                          datetime.now(timezone.utc).date().isoformat(), DAILY_REQUESTS))
