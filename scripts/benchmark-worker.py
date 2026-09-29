"""Compare supported Codex context settings on identical fictional input."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from joblazy.common import ROOT,read_json,write_json
from joblazy.model import CodexModel
from joblazy.materials import obj
output=ROOT/'runtime/worker-benchmark'
for compact in (False,True):
    folder=output/('compact' if compact else 'default')
    model=CodexModel(folder,compact=compact)
    answer=model.generate('Return the sum of the supplied integers.',{'integers':[2,5,7]},obj({'sum':{'type':'integer'}}))
    if answer!={'sum':14}: raise RuntimeError('Worker returned incorrect sum')
report={name:[read_json(p) for p in (output/name).glob('*.meta.json')] for name in ('default','compact')}
write_json(output/'report.json',report);print(json.dumps(report,indent=2))
