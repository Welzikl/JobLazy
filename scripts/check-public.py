"""Audit publishable files; source-only folders require an explicit inventory mode."""
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PRIVATE_DIRS={'local','runtime','.venv','node_modules','.hermes'}


def inventory(root,source_tree=False):
    failures=[]
    if source_tree:
        paths=[]
        for directory,dirs,files in os.walk(root):
            for name in list(dirs):
                if not (Path(directory)/name).resolve().is_relative_to(root):
                    failures.append(((Path(directory)/name).relative_to(root).as_posix(),'directory resolves outside source root'))
                    dirs.remove(name)
                elif name.casefold() in PRIVATE_DIRS|{'.git'}:
                    failures.append(((Path(directory)/name).relative_to(root).as_posix(),'private/generated directory in source export'))
                    dirs.remove(name)
                elif name=='__pycache__':dirs.remove(name)
            paths.extend((Path(directory)/name).relative_to(root).as_posix() for name in files if not name.endswith('.pyc'))
    else:
        git=shutil.which('git') or 'git'
        try:
            probe=subprocess.run([git,'rev-parse','--show-toplevel'],cwd=root,capture_output=True,text=True)
            if probe.returncode or Path(probe.stdout.strip()).resolve()!=root.resolve():
                raise ValueError('Not a standalone Git checkout. Audit a clean ZIP extraction with --source-tree before creating runtime folders.')
            result=subprocess.run([git,'ls-files','--cached','--others','--exclude-standard','-z'],cwd=root,capture_output=True,check=True)
            paths=[p for p in result.stdout.decode().split('\0') if p]
        except OSError as e:raise ValueError('Git is unavailable. Use --source-tree for a clean source export.') from e
    if not paths:raise ValueError('No source files were inventoried; audit cannot succeed')
    return sorted(set(paths)),failures


def audit(root,source_tree=False,private_profile=None):
    root=Path(root).resolve();paths,failures=inventory(root,source_tree)
    secrets=[];profile=Path(private_profile) if private_profile else root/'local/profile.json'
    if private_profile or profile.exists():
        candidate=json.loads(profile.read_text(encoding='utf-8-sig'))['resume']['candidate']
        secrets=[str(candidate.get(k,'')) for k in ('name','email','phone','linkedin') if candidate.get(k)]
    for name in paths:
        p=root/name
        if any(part.casefold() in PRIVATE_DIRS for part in Path(name).parts):
            failures.append((name,'private/generated directory is tracked'));continue
        if not p.resolve().is_relative_to(root):
            failures.append((name,'file resolves outside source root'));continue
        if not p.is_file():
            failures.append((name,'inventoried file is missing'));continue
        if p.name.casefold()=='.git' or p.name.startswith('.env') or p.suffix.lower() in ('.sqlite','.sqlite3','.db'):
            failures.append((name,'environment or database file in source export'))
        content=p.read_text(encoding='utf-8-sig',errors='replace')
        if any(s.casefold() in content.casefold() for s in secrets):failures.append((name,'contains a private profile value'))
        if re.search(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',content):failures.append((name,'private key material'))
        if re.search(r'\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}\b',content):failures.append((name,'possible API key'))
    return {'checked_files':len(paths),'private_profile_checked':bool(secrets),'failures':failures}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-tree',action='store_true',help='Audit a clean source folder without Git; private/generated folders are failures')
    parser.add_argument('--private-profile',help='Optional private profile outside an exported source tree')
    args=parser.parse_args()
    try:result=audit(Path(__file__).resolve().parents[1],args.source_tree,args.private_profile)
    except (ValueError,OSError,KeyError) as e:parser.exit(1,json.dumps({'error':str(e)})+'\n')
    print(json.dumps(result,indent=2));raise SystemExit(bool(result['failures']))
