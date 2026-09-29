"""Verify retained source bytes against existing manifests without rewriting them."""
import hashlib
import json
from pathlib import Path


def verify(root):
    root=Path(root);reports=[]
    for vendor,manifest,kind in [('personal-jobpilot','personal-jobpilot-source.json','gitBlob'),('career-ops','career-ops-source.json','sha256')]:
        directory=(root/'vendor'/vendor).resolve()
        record=json.loads((root/'vendor'/manifest).read_text(encoding='utf-8-sig'))
        expected={f['path'] for f in record['files']}
        actual={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
        mismatches=[]
        for entry in record['files']:
            path=(directory/entry['path']).resolve()
            if not path.is_relative_to(directory) or not path.is_file():mismatches.append(entry['path']);continue
            raw=path.read_bytes()
            value=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() if kind=='gitBlob' else hashlib.sha256(raw).hexdigest()
            if value!=entry[kind]:mismatches.append(entry['path'])
        reports.append({'vendor':vendor,'files':len(expected),'missing':sorted(expected-actual),'extra':sorted(actual-expected),
            'hash_mismatches':mismatches,'license_retained':'LICENSE' in expected and 'LICENSE' in actual})
    return reports


if __name__=='__main__':
    reports=verify(Path(__file__).resolve().parents[1]);print(json.dumps(reports,indent=2))
    raise SystemExit(any(r['missing'] or r['extra'] or r['hash_mismatches'] or not r['license_retained'] for r in reports))
