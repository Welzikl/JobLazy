"""Build an audited, deterministic source ZIP without Git history or private data."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitattributes', '.gitignore', 'AGENTS.md', 'LICENSE', 'README.md',
              'THIRD_PARTY.md', 'VERSION', 'Setup.cmd', 'Start JobLazy.cmd',
              'requirements.txt', 'requirements.lock.txt', 'CLAUDE.md', 'START HERE.txt'}
SOURCE_DIRS = {'.github', 'docs', 'examples', 'joblazy', 'scripts', 'tests', 'vendor', 'skills'}
AGENT_FILES = {'.agents/skills/joblazy/SKILL.md', '.claude/skills/joblazy/SKILL.md'}
EXCLUDED = {'docs/STATUS-HISTORY-2026-09-14.md'}
REQUIRED_RULE_FILES = {'joblazy/runtime-rules.md', 'joblazy/worker-instructions.md',
                       'joblazy/search-worker-instructions.md'}


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(output):
    version = (ROOT/'VERSION').read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', version):
        raise ValueError('VERSION must contain a safe semantic version')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output/f'JobLazy-{version}-windows.zip'
    if target.exists():
        raise ValueError('Release already exists; preserve it and choose a new version/output directory')
    # This narrowly scoped trust exception does not alter the user's Git config.
    git = ['git', '-c', f'safe.directory={ROOT.as_posix()}']
    probe = subprocess.run(git+['rev-parse', '--show-toplevel'], cwd=ROOT,
                           capture_output=True, text=True, check=True)
    if Path(probe.stdout.strip()).resolve() != ROOT:
        raise ValueError('Build from the standalone development repository')
    inventory = subprocess.run(git+['ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                               cwd=ROOT, capture_output=True, check=True)
    paths = sorted(set(inventory.stdout.decode('utf-8').split('\0'))-{''}-EXCLUDED)
    if not (ROOT_FILES | REQUIRED_RULE_FILES | AGENT_FILES).issubset(paths):
        raise ValueError('Required release files are missing from the source inventory')
    with tempfile.TemporaryDirectory(prefix='joblazy-release-') as temp:
        export = Path(temp)
        entries = []
        for name in paths:
            relative = Path(name)
            if name not in ROOT_FILES | AGENT_FILES and relative.parts[0] not in SOURCE_DIRS:
                raise ValueError(f'Unexpected source path needs review: {name}')
            source = ROOT/relative
            if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
                raise ValueError(f'Source path escapes release root: {name}')
            raw = source.read_bytes()
            destination = export/relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            entries.append({'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        profile = ROOT/'local/profile.json'
        audit = load_script('check-public').audit(export, source_tree=True,
                    private_profile=profile if profile.exists() else None)
        if audit['failures']:
            raise ValueError('Release source audit failed: '+json.dumps(audit))
        vendor = load_script('verify-vendor').verify(export)
        if any(not row['license_retained'] or row.get('missing') or row.get('extra')
               or row['hash_mismatches'] for row in vendor):
            raise ValueError('Vendor verification failed: '+json.dumps(vendor))
        manifest = {'version': version, 'files': entries,
                    'excluded': sorted(EXCLUDED), 'git_history_included': False,
                    'note': 'Manifest lists source files; it does not hash itself. Tests are documented separately.'}
        (export/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
        prefix = f'JobLazy-{version}/'
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for file in sorted(export.rglob('*')):
                if not file.is_file(): continue
                item = zipfile.ZipInfo(prefix+file.relative_to(export).as_posix(), (2026, 1, 1, 0, 0, 0))
                item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = 0o100644 << 16
                archive.writestr(item, file.read_bytes())
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix+'.sha256').write_text(checksum+'  '+target.name+'\n', encoding='ascii')
    return {'artifact': str(target), 'sha256': checksum, 'source_files': len(entries),
            'source_audit': audit, 'vendor': vendor}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'runtime/releases')
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
