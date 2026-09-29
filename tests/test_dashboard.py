import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

from joblazy.common import write_json
from joblazy.dashboard import dashboard_data, make_handler, tracker_csv
from joblazy.store import Store
from .support import example_profile, job


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "runtime"; self.data.mkdir()
        self.profile_path = Path(self.temp.name) / "profile.json"; write_json(self.profile_path, example_profile())
        write_json(Path(self.temp.name) / "preparation-policy.json", {"paused": False})
        with closing(Store(self.data / "jobs.sqlite")) as store:
            ranked_job = job("https://example.test/ranked", "Strategy & Operations Associate"); ranked_job["ats"] = "ashby"
            ranked = store.ingest(ranked_job)
            store.transition(ranked, "ranked", {"ranking": {"score": 82, "reason": "Fictional target role"}})
            lower_job = job("https://example.test/lower", "Growth Operations Associate"); lower_job["ats"] = "greenhouse"
            lower = store.ingest(lower_job)
            store.transition(lower, "ranked", {"ranking": {"score": 64, "reason": "Fictional stretch role"}})
            workday_job = job("https://example.test/workday", "Commercial Operations Analyst"); workday_job["ats"] = "workday"
            workday = store.ingest(workday_job)
            store.transition(workday, "ranked", {"ranking": {"score": 72, "reason": "Fictional Workday role"}})
            teamtailor_job = job("https://example.test/teamtailor", "Partnerships Associate"); teamtailor_job["ats"] = "teamtailor"
            teamtailor = store.ingest(teamtailor_job)
            store.transition(teamtailor, "ranked", {"ranking": {"score": 70, "reason": "Fictional Teamtailor role"}})
            failed = store.ingest(job("https://example.test/failed", "Business Development Representative"))
            store.transition(failed, "model_failed", {"reason": "Fictional model failure"})
            intern = store.ingest(job("https://example.test/intern", "Product Operations Intern"))
            store.transition(intern, "retryable", {"reason": "Fictional retry"})
            manual = store.ingest(job("https://example.test/manual", "Prepared Operations Role"))
            store.transition(manual, "manual_review", {"reason": "Fictional ready-for-review handoff"})

    @patch("joblazy.dashboard.CodexModel.status", return_value={"available": True, "detail": "Fixture"})
    def test_data_exposes_review_state_without_candidate_documents(self, _status):
        report = dashboard_data(self.data, self.profile_path)
        self.assertFalse(report["preparation"]["paused"])
        self.assertEqual(report["jobs"][0]["title"], "Strategy & Operations Associate")
        self.assertTrue(report["jobs"][0]["can_prepare"])
        self.assertNotIn("Business Development Representative", [card["title"] for card in report["jobs"]])
        manual = next(card for card in report["jobs"] if card["title"] == "Prepared Operations Role")
        self.assertEqual(manual["status"], "manual_review")
        self.assertFalse(manual["can_prepare"])
        self.assertEqual(report["summary"]["total"], 7)

    @patch("joblazy.dashboard.CodexModel.status", return_value={"available": True, "detail": "Fixture"})
    def test_fresh_profile_without_policy_matches_cli_preparation_default(self, _status):
        (Path(self.temp.name) / "preparation-policy.json").unlink()
        report = dashboard_data(self.data, self.profile_path)
        self.assertFalse(report["preparation"]["paused"])
        self.assertTrue(next(card for card in report["jobs"] if card["status"] == "ranked")["can_prepare"])

    @patch("joblazy.dashboard.CodexModel.status", return_value={"available": True, "detail": "Fixture"})
    def test_queue_views_and_fit_sorts_are_explicit(self, _status):
        highest = dashboard_data(self.data, self.profile_path, "fit_desc")
        lowest = dashboard_data(self.data, self.profile_path, "fit_asc")
        ready = dashboard_data(self.data, self.profile_path, "ready")
        ats = dashboard_data(self.data, self.profile_path, "ats")
        self.assertEqual([row["score"] for row in highest["jobs"][:2]], [82, 72])
        self.assertEqual([row["score"] for row in lowest["jobs"][:2]], [64, 70])
        self.assertEqual({row["status"] for row in ready["jobs"]}, {"ranked", "retryable"})
        self.assertEqual({row["ats"] for row in ats["jobs"]}, {"ashby", "greenhouse", "workday", "teamtailor"})

    @patch("joblazy.dashboard.CodexModel.status", return_value={"available": True, "detail": "Fixture"})
    def test_ats_inventory_includes_discovered_roles_beyond_the_shortlist_limit(self, _status):
        with closing(Store(self.data / "jobs.sqlite")) as store:
            for index in range(35):
                posting=job(f"https://example.test/ats-{index}", f"Discovered ATS role {index}"); posting["ats"]="ashby"; store.ingest(posting)
        report=dashboard_data(self.data,self.profile_path,"ats")
        self.assertGreaterEqual(len(report["jobs"]),39)
        self.assertIn("Discovered ATS role 34",[card["title"] for card in report["jobs"]])

    def test_tracker_export_contains_every_saved_role_and_latest_status(self):
        with closing(Store(self.data / "jobs.sqlite")) as store:
            key = next(row["id"] for row in store.list() if row["status"] == "ranked")
            store.transition(key, "submitted", {"note": "Fictional employer receipt"})
        exported = tracker_csv(self.data)
        self.assertIn("company,title,location,source_ats,status", exported)
        self.assertIn("Strategy & Operations Associate", exported)
        self.assertIn("submitted", exported)
        self.assertIn("Fictional employer receipt", exported)

    @patch("joblazy.dashboard.codex_login_command", return_value=["fixture-codex", "login"])
    @patch("joblazy.dashboard.CodexModel.status", return_value={"available": True, "detail": "Fixture"})
    def test_local_page_requires_token_for_connect_action(self, _status, _command):
        launched=[]; server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.data, self.profile_path, "fixture-token", launched.append))
        thread=threading.Thread(target=server.serve_forever, daemon=True); thread.start(); self.addCleanup(server.server_close)
        try:
            connection=HTTPConnection("127.0.0.1",server.server_port)
            connection.request("GET","/"); response=connection.getresponse(); page=response.read().decode(); self.assertEqual(response.status,200)
            self.assertIn("JobLazy",page); self.assertIn("fixture-token",page)
            connection.request("POST","/api/connect",body="{}",headers={"Content-Type":"application/json"})
            self.assertEqual(connection.getresponse().status,403)
            connection.request("POST","/api/connect",body="{}",headers={"Content-Type":"application/json","X-JobLazy-Token":"fixture-token"})
            response=connection.getresponse(); self.assertEqual(response.status,200); self.assertIn("sign-in opened",response.read().decode())
            self.assertEqual(launched, [["fixture-codex","login"]])
        finally:
            server.shutdown(); thread.join()

    def test_review_page_renders_fit_reason_and_protects_verified_cv_with_local_token(self):
        from playwright.sync_api import sync_playwright
        from joblazy.pipeline import run_queue
        from .support import FixtureModel, fixture_server, job
        with sync_playwright() as pw:
            import os
            channel=os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL','chrome')
            browser=pw.chromium.launch(headless=True,**({'channel':channel} if channel!='chromium' else {}))
            try:
                with fixture_server() as (origin, _):
                    with closing(Store(self.data/'jobs.sqlite')) as store:
                        key=store.ingest(job(origin+'/success', 'Reviewed fixture role'))
                        run_queue(store,example_profile(),FixtureModel(),browser,self.data/'applications',1,only=key,fixture_origin=origin)
                    server=__import__('http.server',fromlist=['ThreadingHTTPServer']).ThreadingHTTPServer(
                        ('127.0.0.1',0),make_handler(self.data,self.profile_path,'fixture-token'))
                    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                    try:
                        with closing(HTTPConnection('127.0.0.1',server.server_port)) as connection:
                            connection.request('GET','/review'); response=connection.getresponse(); page=response.read().decode()
                            self.assertEqual(response.status,200);self.assertIn('Reviewed fixture role',page);self.assertIn('Tailored CV',page)
                            connection.request('GET',f'/review/cv/{key}'); response=connection.getresponse();response.read()
                            self.assertEqual(response.status,403)
                            connection.request('GET',f'/review/cv/{key}?token=fixture-token'); response=connection.getresponse();body=response.read()
                            self.assertEqual(response.status,200);self.assertEqual(response.getheader('Content-Type'),'application/pdf');self.assertTrue(body.startswith(b'%PDF'))
                    finally:server.shutdown();server.server_close();thread.join()
            finally:browser.close()

    @patch("joblazy.dashboard.CodexModel.status", return_value={"available": True, "detail": "Fixture"})
    def test_local_page_starts_only_an_explicitly_requested_preparation(self, _status):
        self.exercise_preparation('personal', 'gpt-5.6-terra')

    def test_friend_preparation_requires_reviewed_cv_through_application_page(self):
        self.exercise_preparation('friend', 'gpt-6-luna')

    def exercise_preparation(self, preset, model):
        launched=[]; server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(
            ("127.0.0.1", 0), make_handler(self.data, self.profile_path, "fixture-token", assist_launcher=launched.append,
                                       model_preset_name=preset))
        thread=threading.Thread(target=server.serve_forever, daemon=True); thread.start(); self.addCleanup(server.server_close)
        try:
            with closing(Store(self.data / "jobs.sqlite")) as store:
                key=next(row["id"] for row in store.list() if row["status"]=="ranked")
            connection=HTTPConnection("127.0.0.1",server.server_port)
            connection.request("POST",f"/api/jobs/{key}/prepare",body="{}",headers={"Content-Type":"application/json","X-JobLazy-Token":"fixture-token"})
            response=connection.getresponse()
            if preset == 'friend':
                self.assertEqual(response.status,409); self.assertIn('confirm the verified CV',response.read().decode())
                self.assertEqual(launched,[])
            else:
                self.assertEqual(response.status,200); self.assertIn("will stop before Submit",response.read().decode())
                self.assertEqual(launched, [[__import__("sys").executable, "-m", "joblazy", "--data", str(self.data.resolve()), "assist", key, "--profile", str(self.profile_path.resolve()), "--browser-channel", "chrome", "--model", model, "--ui-session"]])
        finally:
            server.shutdown(); thread.join()
