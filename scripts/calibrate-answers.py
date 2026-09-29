"""Real-model application prose calibration. No employer browser or form requests."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from joblazy.common import read_json,write_json
from joblazy.model import CodexModel
from joblazy.mapping import plan_fields
from joblazy.narratives import AnswerDrafter

parser=argparse.ArgumentParser()
parser.add_argument('jobs');parser.add_argument('--profile',default='local/profile.json')
parser.add_argument('--output',default='runtime/answer-calibration')
args=parser.parse_args()
profile=read_json(args.profile);job=read_json(args.jobs)[0];output=Path(args.output)
model=CodexModel(output/'model-cache')
fields=[{'id':str(i),'label':question,'required':True,'type':'textarea','max_length':1800} for i,question in enumerate([
    'Describe your relevant experience improving partner operations or reporting.',
    'Do you have experience selling API or technical products to engineering teams? If yes, please describe in a few sentences.',
    'Why are you interested in this role?',
    'Describe when you can start and your availability.',
])]
drafter=AnswerDrafter(profile,job,model,output,job['url'])
plan=drafter.extend(plan_fields(fields,profile,job['url']))
report={'live_model':True,'model':model.model,'employer_forms_opened':False,'job_title':job['title'],
    'answered':[f['id'] for f in plan['fields']],'unresolved':plan['unresolved'],'draft_count':len(drafter.records)}
write_json(output/'report.json',report)
print(json.dumps(report,indent=2))
