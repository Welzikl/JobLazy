"""Honor an operator pause without disabling discovery, ranking or local fixtures."""
from pathlib import Path
from .common import ROOT,NeedsInput,read_json

class PreparationPaused(NeedsInput):
    pass

def require_application_work(data,profile_path=None):
    data=Path(data).resolve()
    paths={data/'preparation-policy.json'}
    if data==(ROOT/'runtime').resolve():paths.add(ROOT/'local/preparation-policy.json')
    if profile_path:paths.add(Path(profile_path).resolve().parent/'preparation-policy.json')
    for path in sorted(paths):
        try:policy=read_json(path)
        except FileNotFoundError:continue
        except (OSError,ValueError) as error:
            raise PreparationPaused(f'Cannot read preparation policy: {path}') from error
        if not isinstance(policy,dict) or type(policy.get('paused',False)) is not bool:
            raise PreparationPaused(f'Invalid preparation pause setting: {path}')
        if policy.get('paused'):
            raise PreparationPaused('Application work is paused. Use --rank-only for discovery and assessment; resume application work only when the user requests it.')
