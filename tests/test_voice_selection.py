import unittest
from voice_selection import select_voice
from narrate import prepare_script

class VoiceTests(unittest.TestCase):
    def test_age(self):
        self.assertEqual(select_voice({'text':'I (25M) had a difficult day.'})[0], 'am_michael')
    def test_female_over_relationship(self):
        self.assertEqual(select_voice({'text':'I (25F) love my girlfriend.'})[0], 'af_heart')
    def test_relationship(self):
        self.assertEqual(select_voice({'text':'My gf helped me move.'})[0], 'am_michael')
    def test_other_person(self):
        self.assertEqual(select_voice({'text':'My brother (25M) moved away.'})[0], 'af_heart')
    def test_both_ages(self):
        self.assertEqual(select_voice({'text':'The wife(22F) and I(22M) went out.'})[0], 'am_michael')
    def test_quote(self):
        self.assertEqual(select_voice({'text':'She said "My husband left me."'})[1], 'no clear narrator clue; channel default')
    def test_linked_hook(self):
        text,_,present=prepare_script({'title':"You won't believe the twenty minutes I just had in the grocery store",'text':'You wont believe the twenty minutes I just had. So Im in the grocery store.'})
        self.assertTrue(present)
        self.assertEqual(text.count('twenty minutes'), 1)
