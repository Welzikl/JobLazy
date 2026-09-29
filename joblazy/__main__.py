import argparse
import json
import os
from pathlib import Path
from .common import ROOT, read_json, NeedsInput
from .store import Store
from .model import CodexModel
from .pipeline import discover, run_queue
from .locking import run_lock
from .profiles import check_profile,load_profile
from .limits import DAILY_JOBS,DAILY_REQUESTS

def main():
    parser = argparse.ArgumentParser(description='JobLazy: discover, tailor and prepare applications using Codex')
    parser.add_argument('--data',default=str(ROOT/'runtime'))
    sub = parser.add_subparsers(dest='command',required=True)
    doctor=sub.add_parser('doctor');doctor.add_argument('--profile',help='Check private profile structure and contact consistency')
    scan = sub.add_parser('scan'); scan.add_argument('boards')
    imp = sub.add_parser('import'); imp.add_argument('jobs')
    profile_import = sub.add_parser('import-profile')
    profile_import.add_argument('source'); profile_import.add_argument('--output',default=str(ROOT/'local/profile.json'))
    status=sub.add_parser('status',help='Summarize queue counts, daily usage and recent results')
    status.add_argument('--limit',type=int,default=20,help='Maximum recent results (default: 20)')
    status.add_argument('--all',action='store_true',help='Print the full legacy job listing, including discovered roles')
    status.add_argument('--profile',help='Check assessment freshness against this current profile')
    usage=sub.add_parser('usage',help='Read recorded model calls, cache reuse and reported tokens; never invokes a model')
    usage.add_argument('--day',help='UTC day YYYY-MM-DD; defaults to today')
    usage.add_argument('--job',help='Limit to one queue job ID')
    coverage=sub.add_parser('coverage',help='Audit saved London discovery coverage without scanning or changing the queue')
    coverage.add_argument('--boards',help='Source configuration to audit')
    coverage.add_argument('--max-age-days',type=int,default=45)
    evaluation=sub.add_parser('evaluate',help='Compare frozen rankings with sourced user judgments; no scanning or model calls')
    evaluation.add_argument('dataset');evaluation.add_argument('--predictions',required=True)
    evaluation.add_argument('--output',required=True);evaluation.add_argument('--top-k',type=int,default=10)
    evaluation.add_argument('--minimum-score',type=int,default=70)
    judgment=sub.add_parser('record-judgment',help='Save one explicit development-set ranking judgment; no model or queue action')
    judgment.add_argument('dataset');judgment.add_argument('id');judgment.add_argument('--output',required=True)
    judgment.add_argument('--decision',required=True,choices=['worthwhile','not-worthwhile'])
    judgment.add_argument('--quote',required=True,help='The user statement supporting this judgment')
    judgment.add_argument('--basis',required=True,help='What the user reviewed, for example full description card')
    judgment.add_argument('--supersede',action='store_true',help='Explicitly replace a prior development judgment in a new dataset copy')
    review=sub.add_parser('review',help='Write a local shortlist with fit reasons and verified CV links')
    review.add_argument('--output');review.add_argument('--limit',type=int,default=100)
    review.add_argument('--bundle',action='store_true',help='Export verified CVs and a portable review ZIP under the data directory')
    review.add_argument('--profile',help='Current private profile, required to verify a bundle')
    dashboard=sub.add_parser('dashboard',help='Open the local JobLazy dashboard')
    dashboard.add_argument('--profile',default=str(ROOT/'local/profile.json'))
    dashboard.add_argument('--host',default='127.0.0.1')
    dashboard.add_argument('--port',type=int,default=8765)
    dashboard.add_argument('--browser-channel',default='chrome',choices=['chrome','msedge','chromium'])
    dashboard.add_argument('--no-open',action='store_true',help='Do not open the local dashboard in a browser')
    dashboard.add_argument('--preset',choices=['personal','friend'],default='personal',
                           help='friend uses Luna for intake, search, review and preparation; personal preserves existing models')
    retry = sub.add_parser('retry'); retry.add_argument('id')
    choose=sub.add_parser('choose',help='Record explicit job interest; never submits or overrides hard exclusions')
    choose.add_argument('id');choose.add_argument('--decision',required=True,choices=['pursue','pass','automatic'])
    choose.add_argument('--note',required=True,help='The user statement supporting this choice')
    show=sub.add_parser('show'); show.add_argument('id');show.add_argument('--profile',help='Refresh unresolved application questions against saved answers')
    inspect=sub.add_parser('inspect',help='Read public application questions; never fill, upload or submit')
    inspect.add_argument('id');inspect.add_argument('--profile',required=True)
    inspect.add_argument('--browser-channel',default='chrome',choices=['chrome','msedge','chromium'])
    answer=sub.add_parser('answer'); answer.add_argument('id'); answer.add_argument('--profile',required=True)
    answer.add_argument('--question',required=True); answer.add_argument('--value',required=True)
    reconcile=sub.add_parser('reconcile',help='Record an outcome you checked; does not submit or retry')
    reconcile.add_argument('id');reconcile.add_argument('--outcome',required=True,choices=['submitted','not-submitted','uncertain'])
    reconcile.add_argument('--note',required=True)
    run = sub.add_parser('run'); run.add_argument('--profile',required=True)
    run.add_argument('--model',default='gpt-5.6-terra'); run.add_argument('--limit',type=int,default=5)
    run.add_argument('--daily-jobs',type=int,default=DAILY_JOBS)
    run.add_argument('--daily-model-requests',type=int,default=DAILY_REQUESTS)
    run.add_argument('--job',help='Process only this saved job ID')
    run_mode=run.add_mutually_exclusive_group()
    run_mode.add_argument('--prepare',action='store_true',help='Fill and upload on live employer sites; stop before submit')
    run_mode.add_argument('--rank-only',action='store_true',help='Assess fit without generating CVs or preparing forms')
    run.add_argument('--browser-channel',default='chrome',choices=['chrome','msedge','chromium'])
    assist=sub.add_parser('assist',help='Prepare one application in a persistent visible browser for manual review')
    assist.add_argument('id');assist.add_argument('--profile',required=True)
    assist.add_argument('--model',default='gpt-5.6-terra')
    assist.add_argument('--ui-session',action='store_true',help='Receive explicit continuation commands from the local dashboard')
    assist.add_argument('--reviewed-cv-sha256',help='Require the exact CV confirmed in the application interface')
    assist.add_argument('--browser-channel',default='chrome',choices=['chrome','msedge','chromium'])
    watch=sub.add_parser('watch',help='Continuously scan and process the queue within daily limits')
    watch.add_argument('--profile',required=True);watch.add_argument('--boards',required=True)
    watch.add_argument('--model',default='gpt-5.6-terra');watch.add_argument('--batch-size',type=int,default=3)
    watch.add_argument('--daily-jobs',type=int,default=DAILY_JOBS);watch.add_argument('--daily-model-requests',type=int,default=DAILY_REQUESTS)
    watch.add_argument('--interval',type=int,default=60);watch.add_argument('--scan-interval',type=int,default=3600)
    watch.add_argument('--max-cycles',type=int)
    watch_mode=watch.add_mutually_exclusive_group()
    watch_mode.add_argument('--prepare',action='store_true')
    watch_mode.add_argument('--rank-only',action='store_true',help='Discover and rank without generating CVs or preparing applications')
    watch.add_argument('--browser-channel',default='chrome',choices=['chrome','msedge','chromium'])
    sub.add_parser('stop',help='Ask the continuous runner to stop after its current cycle')
    args = parser.parse_args()
    data = Path(args.data).resolve()
    if args.command=='usage':
        from .usage import summarize
        try:result=summarize(data/'model-cache',args.day,args.job)
        except ValueError as error:parser.error(str(error))
        print(json.dumps(result,indent=2));return
    if args.command=='evaluate':
        from .evaluation import evaluate_files
        print(json.dumps(evaluate_files(args.dataset,args.predictions,args.output,top_k=args.top_k,minimum_score=args.minimum_score),indent=2));return
    if args.command=='record-judgment':
        from .calibration import record_judgment
        print(json.dumps(record_judgment(args.dataset,args.output,args.id,args.decision=='worthwhile',args.quote,args.basis,
            supersede=args.supersede),indent=2));return
    if args.command=='assist':
        from .assist import run_assisted
        result=run_assisted(data,args.id,args.profile,args.model,args.browser_channel,ui_session=args.ui_session,
                            reviewed_cv_sha256=args.reviewed_cv_sha256)
        print(json.dumps(result,indent=2));return
    if args.command=='stop':
        data.mkdir(parents=True,exist_ok=True);(data/'STOP').write_text('Stop requested\n',encoding='utf-8')
        print(json.dumps({'stop_requested':True,'data':str(data)}));return
    if args.command=='watch':
        from .worker import Worker
        if args.max_cycles is not None and args.max_cycles<1: parser.error('--max-cycles must be positive')
        worker=Worker(data,args.profile,args.boards,model_name=args.model,batch_size=args.batch_size,
            daily_jobs=args.daily_jobs,daily_model_requests=args.daily_model_requests,interval=args.interval,
            scan_interval=args.scan_interval,prepare=args.prepare,rank_only=args.rank_only,browser_channel=args.browser_channel)
        try:result=worker.run(args.max_cycles,emit=lambda report:print(json.dumps(report),flush=True))
        except KeyboardInterrupt:result={'state':'stopped','reason':'Interrupted by operator'}
        print(json.dumps(result));return
    if args.command == 'import-profile':
        from .import_profile import import_profile
        print(json.dumps(import_profile(args.source,args.output),indent=2)); return
    if args.command == 'doctor':
        try: status = CodexModel(data/'model-cache').status()
        except NeedsInput as e: status = {'available':False,'detail':str(e)}
        report={'codex':status,'data':str(data),'runtime_model':'gpt-5.6-terra'}
        if args.profile:
            try:report['profile']=check_profile(read_json(args.profile))
            except (OSError,ValueError):report['profile']={'valid':False,'errors':[{'path':'(profile)','message':'Could not read a valid JSON profile'}],'warnings':[]}
        print(json.dumps(report,indent=2))
        if args.profile and not report['profile']['valid']:raise SystemExit(1)
        return
    if args.command=='dashboard':
        if not 1<=args.port<=65535:parser.error('--port must be between 1 and 65535')
        from .dashboard import serve
        try:serve(data,args.profile,args.host,args.port,open_browser=not args.no_open,browser_channel=args.browser_channel,
                  model_preset_name=args.preset)
        except ValueError as error:parser.error(str(error))
        return
    store = Store(data/'jobs.sqlite')
    try:
        if args.command=='coverage':
            from .coverage import write_coverage
            if args.max_age_days<1:parser.error('--max-age-days must be positive')
            print(json.dumps(write_coverage(store,data,args.boards,args.max_age_days),indent=2));return
        if args.command == 'status':
            if args.limit<1:parser.error('--limit must be positive')
            if args.all:
                result=[{'id':r['id'],'title':r['data']['title'],'status':r['status'],'result':r['result']} for r in store.list()]
            else:
                from .status import summary
                result=summary(store,args.limit,profile=load_profile(args.profile) if args.profile else None)
            print(json.dumps(result,indent=2));return
        if args.command == 'show':
            from .answers import questions
            print(json.dumps(questions(store,args.id,data/'applications'/args.id,load_profile(args.profile) if args.profile else None),indent=2)); return
        with run_lock(data/'run.lock'):
            if args.command == 'review':
                from .review import render_review
                if args.limit<1:parser.error('--limit must be positive')
                if args.bundle:
                    if not args.profile:parser.error('--bundle requires --profile to verify saved material inputs')
                    if args.output:parser.error('--bundle writes review-bundle.zip in --data; --output is only for HTML reviews')
                    from .bundle import bundle_review
                    result=bundle_review(store,data,load_profile(args.profile),args.limit)
                else:result=render_review(store,data,args.output,args.limit,profile=load_profile(args.profile) if args.profile else None)
            elif args.command == 'scan': result = discover(args.boards,store,data/'last-scan.json')
            elif args.command == 'inspect':
                from playwright.sync_api import sync_playwright
                from .inspection import inspect_application
                profile=load_profile(args.profile)
                with sync_playwright() as pw:
                    options={'headless':True}
                    if args.browser_channel!='chromium':options['channel']=args.browser_channel
                    browser=pw.chromium.launch(**options)
                    try:result=inspect_application(store,args.id,profile,browser,data/'applications'/args.id)
                    finally:browser.close()
                from .review import render_review
                render_review(store,data,profile=profile)
            elif args.command == 'import':
                jobs = read_json(args.jobs)
                result = {'ids':[store.ingest(j) for j in (jobs['jobs'] if isinstance(jobs,dict) else jobs)]}
            elif args.command == 'retry':
                store.transition(args.id,'retryable',{'reason':'Explicit operator retry'},expected={'assessment_failed','model_failed','processing_failed','needs_input','retryable','materials_ready','prepared','posting_closed','posting_expired','posting_unavailable'})
                result = {'id':args.id,'status':'retryable'}
            elif args.command == 'choose':
                result=store.record_choice(args.id,args.decision,args.note)
            elif args.command == 'answer':
                from .answers import save_answer
                result=save_answer(store,args.id,data/'applications'/args.id,args.profile,args.question,args.value)
                from .review import render_review
                render_review(store,data,profile=load_profile(args.profile))
            elif args.command == 'reconcile':
                store.recover()
                result=store.reconcile(args.id,args.outcome,args.note)
                from .common import write_json
                write_json(data/'applications'/args.id/'manual-outcome.json',result)
                from .review import render_review
                render_review(store,data)
            elif args.command == 'run':
                from .work_mode import require_application_work
                from .worker import utc_day
                if args.limit<1 or args.daily_jobs<1 or args.daily_model_requests<1:
                    parser.error('Run limits must be positive')
                day=utc_day();usage=store.daily_usage(day)
                if usage['job_attempts']>=args.daily_jobs or usage['model_requests']>=args.daily_model_requests:
                    result={'state':'daily_limit','day':day,'mode':'rank_only' if args.rank_only else 'prepare' if args.prepare else 'cv_only',
                        'results':[],'usage':usage,'limits':{'daily_jobs':args.daily_jobs,'daily_model_requests':args.daily_model_requests}}
                    print(json.dumps(result,indent=2));return
                if not args.rank_only:require_application_work(data,args.profile)
                from playwright.sync_api import sync_playwright
                profile = load_profile(args.profile)
                if args.prepare and profile.get('example_only',True):
                    raise NeedsInput('Fictional example profiles cannot be used on employer sites')
                model = CodexModel(data/'model-cache',args.model,
                    before_request=lambda:store.reserve_model_request(utc_day(),args.daily_model_requests))
                with sync_playwright() as pw:
                    launch = {'headless':True}
                    if args.browser_channel != 'chromium': launch['channel'] = args.browser_channel
                    browser = pw.chromium.launch(**launch)
                    try:
                        result = run_queue(store,profile,model,browser,data/'applications',min(args.limit,args.daily_jobs-usage['job_attempts']),
                            prepare=args.prepare,allow_live=args.prepare,only=args.job,rank_only=args.rank_only,profile_path=args.profile)
                    finally: browser.close()
                from .review import render_review
                render_review(store,data,profile=profile)
            print(json.dumps(result,indent=2))
    finally: store.close()

if __name__ == '__main__': main()
