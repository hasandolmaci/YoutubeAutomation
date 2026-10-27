"""Offline tests: no uploads or OAuth requests are made."""
import json
import sys
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import channel_config as channels
import produce_batch
import scheduler
import upload_next

class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=channels.ROOT/'output',prefix='channel_test_')
        self.root=Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(channels.ROOT/'output'))
        self.patches=[patch.object(channels,'ROOT',self.root),patch.object(channels,'CHANNELS',self.root/'channels'),patch.object(channels,'SHARED',self.root/'shared')]
        for p in self.patches:p.start()
        channels.create_channel('main','Main')
        channels.create_channel('second','Second')
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def test_profiles_isolate_credentials_and_media(self):
        self.assertEqual(channels.paths('main')['videos'],self.root/'videos')
        self.assertEqual(channels.paths('second')['credentials'],self.root/'channels/second/credentials')
        self.assertFalse(channels.load_channel('second')['schedule']['enabled'])
        with self.assertRaises(ValueError):channels.create_channel('../outside','Bad')
    def test_fingerprint_and_global_lock(self):
        self.assertEqual(channels.story_fingerprint('Same   STORY'),channels.story_fingerprint('same story'))
        with channels.lock('production'):
            with self.assertRaises(RuntimeError):
                with channels.lock('production'):pass
        self.assertFalse((channels.SHARED/'production.lock').exists())
    def test_wrong_google_channel_is_rejected(self):
        c=channels.load_channel('main');c['youtube_channel_id']='expected';channels.write_json(channels.CHANNELS/'main/config.json',c)
        token=channels.paths('main')['credentials']/'channel_token.json';token.write_text('{}')
        creds=SimpleNamespace(expired=False,valid=True)
        api=MagicMock();api.__enter__.return_value=api
        api.channels.return_value.list.return_value.execute.return_value={'items':[{'id':'wrong','snippet':{'title':'Wrong'}}]}
        with patch('google.oauth2.credentials.Credentials.from_authorized_user_file',return_value=creds),patch('googleapiclient.discovery.build',return_value=api):
            with self.assertRaisesRegex(RuntimeError,'Wrong YouTube channel'):channels.credentials_for('main')
    def test_used_videos_and_uncertain_uploads(self):
        folder=self.root/'videos'/'batch';folder.mkdir(parents=True)
        video=folder/'story.mp4';video.write_bytes(b'video')
        channels.write_json(folder/'batch.json',[{'video':video.name,'title':'Exact title','status':'complete'}])
        self.assertEqual(upload_next.select_video(folder,{})[3],'Exact title')
        digest=upload_next.fingerprint(video)
        with self.assertRaises(RuntimeError):upload_next.select_video(folder,{digest:{'status':'uploading'}})
        self.assertIsNone(upload_next.select_video(folder,{digest:{'status':'uploaded'}}))
        self.assertTrue((folder/'story_used.mp4').exists())
    def test_production_settings_and_cross_channel_duplicates(self):
        bg=self.root/'backgrounds';bg.mkdir();(bg/'background_000.mp4').write_bytes(b'background')
        story={'id':'abc','title':'A story','text':' '.join(['hello']*70),'text_source':'post_page'}
        for id in ('main','second'):channels.write_json(channels.paths(id)['stories']/'abc.json',story)
        c=channels.load_channel('main');c['voice']='am_adam';channels.write_json(channels.CHANNELS/'main/config.json',c)
        voices=[]
        def narration():
            voices.append(sys.argv[sys.argv.index('--voice')+1]);folder=Path(sys.argv[sys.argv.index('--output')+1]);folder.mkdir(parents=True);channels.write_json(folder/'metadata.json',{'duration_seconds':35})
        def command(args,**kwargs):
            if '--destination' in args:
                target=Path(args[args.index('--destination')+1]);name=args[args.index('--name')+1];(target/(name+'_yellow_words.mp4')).write_bytes(b'rendered')
            return SimpleNamespace(returncode=0)
        common=[patch.object(produce_batch,'ROOT',self.root),patch.object(produce_batch,'SHARED',channels.SHARED),patch.object(produce_batch.narrate,'main',narration),patch.object(produce_batch.subprocess,'run',command)]
        for p in common:p.start()
        try:
            with patch.object(sys,'argv',['produce_batch.py','--channel','main','--count','1','--batch','test']):produce_batch.main()
            self.assertEqual(voices,['am_adam'])
            self.assertTrue((channels.paths('main')['stories']/'abc_used.json').exists())
            with patch.object(sys,'argv',['produce_batch.py','--channel','second','--count','1','--batch','test']):
                with self.assertRaisesRegex(RuntimeError,'Only 0 eligible'):produce_batch.main()
        finally:
            for p in reversed(common):p.stop()
    def test_scheduler_due_slot_once(self):
        c=channels.load_channel('second');c['schedule'].update(enabled=True,timezone='Europe/Berlin',times=['10:00']);channels.write_json(channels.CHANNELS/'second/config.json',c)
        (channels.paths('second')['credentials']/'channel_token.json').write_text('{}')
        now=datetime(2026,10,22,8,0,tzinfo=timezone.utc)
        with patch.object(scheduler,'CHANNELS',channels.CHANNELS),patch.object(scheduler,'SHARED',channels.SHARED),patch.object(scheduler.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            scheduler.tick(now=now);scheduler.tick(now=now)
            self.assertEqual(run.call_count,1)
            self.assertIn('second',run.call_args.args[0])

if __name__=='__main__':unittest.main()
