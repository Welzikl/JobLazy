import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)

class NeedsInput(Exception):
    pass

class DailyJobLimit(NeedsInput):
    """No new processing attempt may start until the next UTC day."""

class PostingDescriptionError(NeedsInput):
    """Public content does not identify the requested role; not a candidate fact gap."""
    def __init__(self,message,evidence_path):
        super().__init__(message)
        self.evidence_path=str(evidence_path)


class InvalidModelOutput(Exception):
    """A response/cache contract failure, never a missing candidate fact."""
    def __init__(self,message,evidence_path=None):
        super().__init__(message)
        self.evidence_path=str(evidence_path) if evidence_path else None

class PostingUnavailable(Exception):
    """A posting observation that stops work without implying candidate ineligibility."""
    def __init__(self, observation):
        super().__init__(observation['reason'])
        self.observation=observation
        self.status=observation['queue_status']

class ModelUnavailable(NeedsInput):
    """A global provider interruption; leave the job resumable, not an answer exception."""

class DailyModelLimit(ModelUnavailable):
    """The local UTC request allowance is exhausted; the provider has not failed."""
