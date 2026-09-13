"""Publishing control flow without registry or Git writes."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import build_images
from resources import REPO, Invalid, input_hash, read, validate


class PublishTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        for name in ['sandbox', 'sandbox-runner']:
            shutil.copytree(REPO/name,self.root/name)
        self.manifest=read(REPO/'resources.yaml')
        self.manifest['sandbox-images']['default']['lock'] = None
        self.original=copy.deepcopy(self.manifest)
        (self.root/'resources.yaml').write_text('unchanged on disk')
        self.source='a'*40
        self.calls=[]
        self.remote=self.source
        def git(*args):
            self.calls.append(args)
            if args == ('git','rev-parse','HEAD'): return self.source
            if args == ('git','rev-parse','origin/main'): return self.remote
            return ''
        self.git=git
        self.addCleanup(patch.stopall)
        patch.object(build_images,'REPO',self.root).start()
        self.validation=patch.object(build_images,'validate',return_value=(self.manifest,[])).start()
        patch.object(build_images,'run',side_effect=self.git).start()
        patch.dict(os.environ,{'GITHUB_REF':'refs/heads/main','GITHUB_ACTIONS':'true',
                              'GITHUB_RUN_ID':'42','GITHUB_RUN_ATTEMPT':'1'}).start()
        patch.object(sys,'argv',['build_images.py']).start()
        def docker(args,check):
            metadata=Path(args[args.index('--metadata-file')+1])
            metadata.write_text(json.dumps({'containerimage.digest':'sha256:'+'b'*64}))
        self.docker=patch.object(build_images.subprocess,'run',side_effect=docker).start()

    def test_success_records_digest_then_validates_and_pushes(self):
        build_images.main()
        data=read(self.root/'resources.yaml')
        lock=data['sandbox-images']['default']['lock']
        self.assertEqual(lock['digest'],'sha256:'+'b'*64)
        self.assertEqual(lock['source-ref'],self.source)
        self.assertEqual(lock['input-hash'],input_hash(self.root,self.original['sandbox-images']['default']))
        self.validation.assert_called_with(ready=True)
        self.assertEqual(self.calls[-1],('git','push','origin','HEAD:main'))
        self.assertIn(('git', 'add', '--', 'resources.yaml'), self.calls)
        args=self.docker.call_args.args[0]
        self.assertIn('--no-cache',args)
        self.assertEqual(args[args.index('--platform')+1],'linux/amd64')

    def test_same_repository_images_get_distinct_tags(self):
        self.manifest['sandbox-images']['second'] = copy.deepcopy(self.manifest['sandbox-images']['default'])
        build_images.main()
        images = read(self.root / 'resources.yaml')['sandbox-images']
        self.assertNotEqual(images['default']['lock']['tag'], images['second']['lock']['tag'])

    def test_unchanged_input_preserves_lock(self):
        for image in self.manifest['sandbox-images'].values():
            image['lock']={'input-hash':input_hash(self.root,image),'digest':'sha256:'+'b'*64}
        build_images.main()
        self.docker.assert_not_called()
        self.assertFalse(any('push' in call for call in self.calls))

    def test_force_rebuild_even_with_matching_hash(self):
        for image in self.manifest['sandbox-images'].values():
            image['lock']={'input-hash':input_hash(self.root,image),'digest':'sha256:'+'b'*64}
        with patch.object(sys,'argv',['build_images.py','--force']): build_images.main()
        self.assertEqual(self.docker.call_count, len(self.manifest['sandbox-images']))

    def test_failed_build_does_not_write_lock(self):
        self.docker.side_effect=subprocess.CalledProcessError(1,['docker'])
        with self.assertRaises(subprocess.CalledProcessError): build_images.main()
        self.assertEqual((self.root/'resources.yaml').read_text(),'unchanged on disk')
        self.assertFalse(any('commit' in call or 'push' in call for call in self.calls))

    def test_main_advancement_rejects_result(self):
        self.remote='c'*40
        with self.assertRaisesRegex(Invalid,'main advanced'): build_images.main()
        self.assertEqual((self.root/'resources.yaml').read_text(),'unchanged on disk')
        self.assertFalse(any('commit' in call or 'push' in call for call in self.calls))

    def test_feature_branch_cannot_publish(self):
        with patch.dict(os.environ,{'GITHUB_REF':'refs/heads/feature'}):
            with self.assertRaisesRegex(Invalid,'main'): build_images.main()
        self.docker.assert_not_called()


if __name__=='__main__': unittest.main()
