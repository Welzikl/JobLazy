"""Persist explicit development-set ranking judgments without inference."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from .common import read_json, write_json
from .evaluation import validate_cases
from .store import choice_job_hash


def record_judgment(dataset_path, output_path, key, worthwhile, quote, basis, *, recorded_at=None, supersede=False):
    """Write one sourced user judgment to a new copy of a frozen dataset.

    Holdout entries are deliberately rejected: saving a label for one would
    expose it to tuning. Superseding a label is explicit, preserves the prior
    record in the output copy, and never mutates its source dataset.
    """
    dataset_path, output_path = Path(dataset_path), Path(output_path)
    if dataset_path.resolve() == output_path.resolve():
        raise ValueError('Judgment output must be a different file from its source dataset')
    if type(worthwhile) is not bool:
        raise ValueError('Worthwhile must be a boolean')
    if not isinstance(quote, str) or not quote.strip():
        raise ValueError('A judgment needs the user quote supporting it')
    if not isinstance(basis, str) or not basis.strip():
        raise ValueError('A judgment needs a review basis')
    source = read_json(dataset_path)
    validate_cases(source)
    dataset = deepcopy(source)
    case = next((item for item in dataset['cases'] if item['id'] == key), None)
    if case is None:
        raise ValueError('Judgment ID does not exist in the dataset')
    if case['split'] != 'development':
        raise ValueError('Only development cases can receive judgments during tuning')
    existing = case.get('judgment')
    if existing is not None and not supersede:
        raise ValueError('This case already has a judgment; preserve it in a new dataset version')
    if recorded_at is None:
        recorded_at = datetime.now().astimezone().isoformat()
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise ValueError('A judgment needs a recording timestamp')
    if existing is not None:
        case.setdefault('judgment_history', []).append(existing)
    case['judgment'] = {
        'worthwhile': worthwhile,
        'job_hash': choice_job_hash(case['job']),
        'source': {'kind': 'user', 'quote': quote.strip(), 'basis': basis.strip(), 'recorded_at': recorded_at},
    }
    validate_cases(dataset)
    write_json(output_path, dataset)
    return {'path': str(output_path.resolve()), 'id': key, 'worthwhile': worthwhile,
            'job_hash': case['judgment']['job_hash'], 'split': case['split'], 'superseded': existing is not None}
