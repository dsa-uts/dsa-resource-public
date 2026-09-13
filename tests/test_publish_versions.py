"""Version publication against a real, local Git remote; no GitHub or registry writes."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish_versions
from resources import Invalid, check_history, input_hash, read, validate

FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'resources'


class VersionPublishTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.remote = self.directory / 'remote.git'
        self.root = self.directory / 'checkout'
        self.git('init', '--bare', '--initial-branch=main', str(self.remote), cwd=self.directory)
        self.git('clone', str(self.remote), str(self.root), cwd=self.directory)
        self.configure(self.root)
        shutil.copytree(FIXTURES / 'valid', self.root, dirs_exist_ok=True)
        shutil.copytree(self.root / 'sample', self.root / 'second')
        self.edit('second/resource.yaml', lambda d: d['resource'].update(id='second'))
        def prepare(manifest):
            manifest['resources'].append({'id': 'second', 'path': 'second/resource.yaml'})
            for image in manifest['sandbox-images'].values():
                image['lock']['input-hash'] = input_hash(self.root, image)
        self.edit('resources.yaml', prepare)
        self.commit('initial resources')
        self.git('push', 'origin', 'HEAD:main')
        self.source = self.git('rev-parse', 'HEAD')
        self.addCleanup(patch.stopall)
        patch.object(publish_versions, 'REPO', self.root).start()
        patch.object(publish_versions, 'validate', side_effect=lambda ready: validate(self.root, ready=ready)).start()
        patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/main', 'GITHUB_ACTIONS': 'true'}).start()

    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd or self.root,
                                       text=True, stderr=subprocess.STDOUT).strip()

    def configure(self, root):
        self.git('config', 'user.name', 'Test', cwd=root)
        self.git('config', 'user.email', 'test@example.invalid', cwd=root)
        self.git('config', 'commit.gpgsign', 'false', cwd=root)
        self.git('config', 'core.hooksPath', '/dev/null', cwd=root)

    def edit(self, name, mutate):
        path = self.root / name
        data = read(path)
        mutate(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False))

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-m', message)

    def histories(self):
        return {e['id']: e.get('versions', []) for e in read(self.root / 'resources.yaml')['resources']}

    def advance_remote(self):
        other = self.directory / 'other'
        self.git('clone', str(self.remote), str(other), cwd=self.directory)
        self.configure(other)
        (other / 'README.md').write_text('concurrent main update')
        self.git('add', '.', cwd=other)
        self.git('commit', '-m', 'concurrent update', cwd=other)
        self.git('push', 'origin', 'HEAD:main', cwd=other)
        return self.git('rev-parse', 'HEAD', cwd=other)

    def test_register_new_and_bumped_resources_without_duplicates(self):
        publish_versions.main()
        for history in self.histories().values():
            self.assertEqual(history, [{'version': 1, 'commit': self.source}])
        old = copy.deepcopy(self.histories())
        self.edit('sample/resource.yaml', lambda d: d['resource'].update(version=4))
        self.edit('resources.yaml', lambda d: d['sandbox-images']['default']['lock'].update(
            digest='sha256:' + 'd'*64, tag='rebuilt'))
        (self.root / 'second/description.md').write_text('unpublished content edit')
        self.commit('release sample only')
        self.git('push', 'origin', 'HEAD:main')
        source = self.git('rev-parse', 'HEAD')
        publish_versions.main()
        self.assertEqual(self.histories()['sample'], old['sample'] + [{'version': 4, 'commit': source}])
        self.assertEqual(self.histories()['second'], old['second'])
        published = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.remote), published)
        self.assertEqual(self.git('status', '--porcelain'), '')
        publish_versions.main()
        self.assertEqual(self.git('rev-parse', 'HEAD'), published)

    def test_content_and_image_updates_without_bump_keep_old_snapshot(self):
        publish_versions.main()
        old = copy.deepcopy(self.histories())
        (self.root / 'sample/description.md').write_text('unpublished correction')
        self.edit('resources.yaml', lambda d: d['sandbox-images']['default']['lock'].update(
            digest='sha256:' + 'd'*64, tag='rebuilt'))
        self.commit('update content and image without a version bump')
        self.git('push', 'origin', 'HEAD:main')
        source = self.git('rev-parse', 'HEAD')
        publish_versions.main()
        self.assertEqual(self.histories(), old)
        self.assertEqual(self.git('rev-parse', 'HEAD'), source)

    def test_unready_image_prevents_registration(self):
        (self.root / 'sandbox/extra').write_text('changed build input')
        self.commit('unready image')
        before = self.git('rev-parse', 'HEAD')
        with self.assertRaisesRegex(Invalid, 'stale image lock'): publish_versions.main()
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertTrue(all(not h for h in self.histories().values()))

    def test_history_is_bot_managed_but_resource_edits_are_allowed(self):
        publish_versions.main()
        base = self.git('rev-parse', 'HEAD')
        manifest = read(self.root / 'resources.yaml')
        self.edit('sample/resource.yaml', lambda d: d['resource'].update(version=2))
        check_history(self.root, manifest, base)
        for history in [[], [{'version': 1, 'commit': 'b'*40}],
                        manifest['resources'][0]['versions'] + [{'version': 2, 'commit': base}]]:
            with self.subTest(history=history):
                changed = copy.deepcopy(manifest)
                changed['resources'][0]['versions'] = history
                with self.assertRaisesRegex(Invalid, 'bot-managed'):
                    check_history(self.root, changed, base)

    def test_main_advancement_before_write_rejects_publication(self):
        remote = self.advance_remote()
        before = (self.root / 'resources.yaml').read_bytes()
        with self.assertRaisesRegex(Invalid, 'main advanced'): publish_versions.main()
        self.assertEqual((self.root / 'resources.yaml').read_bytes(), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.source)
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.remote), remote)

    def test_main_advancement_after_fetch_is_rejected_by_push(self):
        original = publish_versions.run
        remote = []
        def race(*args):
            if args == ('git', 'push', 'origin', 'HEAD:main'):
                remote.append(self.advance_remote())
            return original(*args)
        with patch.object(publish_versions, 'run', side_effect=race):
            with self.assertRaises(subprocess.CalledProcessError): publish_versions.main()
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.remote), remote[0])
        manifest = yaml.safe_load(self.git('show', 'main:resources.yaml', cwd=self.remote))
        self.assertTrue(all(not e.get('versions') for e in manifest['resources']))

    def test_dirty_checkout_or_non_main_cannot_publish(self):
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/feature'}):
            with self.assertRaisesRegex(Invalid, 'restricted to main'): publish_versions.main()
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}):
            with self.assertRaisesRegex(Invalid, 'restricted to Actions'): publish_versions.main()
        (self.root / 'uncommitted').write_text('draft')
        with self.assertRaisesRegex(Invalid, 'clean checkout'): publish_versions.main()
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.remote), self.source)


if __name__ == '__main__':
    unittest.main()
