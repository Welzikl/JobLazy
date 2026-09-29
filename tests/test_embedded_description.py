import unittest
from types import SimpleNamespace
from joblazy.common import NeedsInput
from joblazy.discovery import greenhouse_job_frame


class EmbeddedDescriptionTests(unittest.TestCase):
    def frame(self,url,visible=True):
        return SimpleNamespace(url=url,is_detached=lambda:False,frame_element=lambda:SimpleNamespace(is_visible=lambda:visible))

    def test_only_visible_matching_greenhouse_job_is_selected(self):
        correct=self.frame('https://job-boards.greenhouse.io/embed/job_app?for=fictional&token=123')
        wrong=self.frame('https://job-boards.greenhouse.io/embed/job_app?for=fictional&token=456')
        unrelated=self.frame('https://example.test/embed/job_app?token=123')
        hidden=self.frame(correct.url,False)
        page=SimpleNamespace(frames=[wrong,unrelated,hidden,correct],main_frame=None)
        self.assertIs(greenhouse_job_frame(page,'https://careers.example.test/?gh_jid=123'),correct)
        for query in ('','?gh_jid=123&gh_jid=456','?gh_jid=bad','?gh_jid=999'):
            self.assertIsNone(greenhouse_job_frame(page,'https://careers.example.test/'+query))

    def test_multiple_matching_frames_are_not_guessed(self):
        page=SimpleNamespace(frames=[self.frame('https://boards.greenhouse.io/embed/job_app?token=123') for _ in range(2)],main_frame=None)
        with self.assertRaises(NeedsInput):greenhouse_job_frame(page,'https://careers.example.test/?gh_jid=123')
