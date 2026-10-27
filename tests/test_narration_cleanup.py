import unittest
from narrate import prepare_script, repetition_review

class CleanupTests(unittest.TestCase):
    def test_repeated_paragraph(self):
        paragraph='This is a complete paragraph with enough words to represent an accidentally pasted story update.'
        script,removed,_=prepare_script({'title':'A title','text':paragraph+'\n\n'+paragraph+'\n\nRead more'})
        self.assertEqual(script.count(paragraph),1)
        self.assertNotIn('Read more',script)
        self.assertEqual(len(removed),1)
    def test_repeated_passage_without_line_breaks(self):
        text='One two three four five six seven eight nine ten eleven twelve thirteen fourteen.'
        script,removed,_=prepare_script({'text':text+' '+text+' '+text},False)
        self.assertEqual(script.strip(),text)
        self.assertTrue(removed)
    def test_title_not_repeated(self):
        script,_,present=prepare_script({'title':'This is my story','text':'This is my story. Something happened next.'})
        self.assertTrue(present)
        self.assertEqual(script.count('This is my story'),1)
    def test_no_word_prefix_false_match(self):
        script,_,present=prepare_script({'title':'He','text':'Hello there.'})
        self.assertFalse(present)
        self.assertTrue(script.startswith('He. Hello'))
    def test_unique_material_preserved(self):
        text='The bus arrived late. A stranger helped me find the right stop. I thanked her.'
        script,removed,_=prepare_script({'text':text},False)
        self.assertEqual(script,text)
        self.assertEqual(removed,[])
    def test_separated_duplicate_sentence(self):
        sentence='I went to the grocery store to buy a jar of pasta sauce.'
        script,removed,_=prepare_script({'text':sentence+' Then I met a stranger. '+sentence},False)
        self.assertEqual(script.count(sentence),1)
        self.assertTrue(removed)
    def test_near_repeat_flagged(self):
        self.assertTrue(repetition_review('I went to the grocery store to buy a large jar of pasta sauce. I went to the grocery store to buy a small jar of pasta sauce.'))
