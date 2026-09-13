"""Resource validation and expansion contract regressions."""
import copy
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from resources import Invalid, expand, image_entries, input_hash, read, validate


FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'resources'


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(FIXTURES / 'valid', self.root, dirs_exist_ok=True)

    def edit(self, fn, name='sample/resource.yaml'):
        path = self.root / name
        data = read(path)
        fn(data)
        path.write_text(yaml.safe_dump(data, allow_unicode=True))

    def test_source_valid_but_first_build_required(self):
        self.edit(lambda m: m['sandbox-images']['default'].update(lock=None), 'resources.yaml')
        validate(self.root)
        with self.assertRaisesRegex(Invalid, 'not been built'): validate(self.root, ready=True)

    def test_ready_and_stale_lock(self):
        manifest, resources = validate(self.root)
        for key, image in manifest['sandbox-images'].items():
            fingerprint = input_hash(self.root, image)
            self.edit(lambda m: m['sandbox-images'][key].update(lock={
                'tag': 'test', 'digest': 'sha256:' + 'a'*64, 'input-hash': fingerprint,
                'source-ref': 'b'*40, 'actions-run-id': '1'}), 'resources.yaml')
        validate(self.root, ready=True)
        before = expand(self.root)
        (self.root/'sample/description.md').write_text('description only')
        validate(self.root, ready=True)
        self.assertEqual(before, expand(self.root))
        (self.root/'sandbox/extra').write_text('new build input')
        with self.assertRaisesRegex(Invalid, 'stale'): validate(self.root, ready=True)

    def test_expansion_deterministic(self):
        before = expand(self.root, ready=False)
        self.edit(lambda d: None)
        self.assertEqual(before, expand(self.root, ready=False))
        result = yaml.safe_load(before)
        for workflow in result['resources'][0]['workflows'].values():
            for job in workflow['jobs'].values():
                self.assertEqual(job['resolved-image']['image'], 'ghcr.io/example/test-sandbox')

    def test_compile_boolean_survives_expansion(self):
        for compile in [True, False]:
            with self.subTest(compile=compile):
                self.edit(lambda d: d['workflows']['main']['jobs']['build']['steps'][0].update(compile=compile))
                result = yaml.safe_load(expand(self.root, ready=False))
                self.assertIs(result['resources'][0]['workflows']['main']['jobs']['build']['steps'][0]['compile'], compile)

    def test_compile_can_be_omitted(self):
        self.edit(lambda d: d['workflows']['main']['jobs']['build']['steps'][0].pop('compile', None))
        result = yaml.safe_load(expand(self.root, ready=False))
        self.assertNotIn('compile', result['resources'][0]['workflows']['main']['jobs']['build']['steps'][0])

    def test_multiline_run_survives_expansion(self):
        script = 'printf "hello\\n" | cat > output.txt\ncat < output.txt\n'
        self.edit(lambda d: d['workflows']['main']['jobs']['public']['steps'][0].update(run=script))
        result = yaml.safe_load(expand(self.root, ready=False))
        self.assertEqual(result['resources'][0]['workflows']['main']['jobs']['public']['steps'][0]['run'], script)

    def test_invalid_definitions(self):
        cases = {
            'unknown-image': 'unknown image',
            'id-mismatch': 'ID mismatch',
            'missing-expected': 'missing or wrong file type: .*missing.txt',
            'cycle': 'dependency cycle',
            'public-private-dependency': 'public Job depends on private Job',
            'unknown-artifact': 'unknown Artifact output',
            'artifact-without-direct-dependency': 'direct dependency',
            'missing-step-timeout': "'step-timeout' is a required property",
            'missing-step-timeout-with-override': "'step-timeout' is a required property",
            'duplicate-yaml-key': 'duplicate or non-string YAML key',
        }
        for field in ['step-timeout', 'timeout']:
            for value in ['zero-seconds', 'zero-milliseconds', 'fractional', 'trailing-newline']:
                cases[f'{field}-{value}'] = 'does not match'
        self.assertEqual(set(cases), {path.name for path in (FIXTURES / 'invalid').iterdir()})
        for name, message in cases.items():
            with self.subTest(fixture=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(FIXTURES / 'valid', root, dirs_exist_ok=True)
                shutil.copytree(FIXTURES / 'invalid' / name, root, dirs_exist_ok=True)
                with self.assertRaisesRegex(Invalid, message):
                    validate(root)

    def test_duration_strings_survive_expansion(self):
        for default, override in [('2s', '300ms'), ('300ms', '2s'), ('1ms', '1000s')]:
            with self.subTest(default=default, override=override):
                def mutate(d):
                    job = d['workflows']['main']['jobs']['public']
                    job['limits']['step-timeout'] = default
                    job['steps'][0]['timeout'] = override
                    job['steps'][1].pop('timeout', None)
                self.edit(mutate)
                result = yaml.safe_load(expand(self.root, ready=False))
                job = result['resources'][0]['workflows']['main']['jobs']['public']
                self.assertEqual(job['limits']['step-timeout'], default)
                self.assertEqual(job['steps'][0]['timeout'], override)
                self.assertNotIn('timeout', job['steps'][1])

    def test_symlink(self):
        path=self.root/'sample/description.md'
        path.unlink(); path.symlink_to(FIXTURES / 'valid/sample/description.md')
        with self.assertRaisesRegex(Invalid, 'symlink'): validate(self.root)

    def test_root_image_resolution(self):
        image = copy.deepcopy(read(self.root / 'resources.yaml')['sandbox-images']['default'])
        image['build']['image'] = 'ghcr.io/dsa-uts/another-sandbox'
        self.edit(lambda d: d['sandbox-images'].update(custom=image), 'resources.yaml')
        self.edit(lambda d: d['workflows']['main']['jobs']['public'].update({'sandbox-image': 'custom'}))
        manifest, _ = validate(self.root)
        entries = list(image_entries(self.root, manifest))
        self.assertEqual({key for key, _, _ in entries}, {'shared/default', 'shared/custom'})
        self.assertTrue(all(base == self.root for _, base, _ in entries))
        result = yaml.safe_load(expand(self.root, ready=False))
        self.assertEqual(result['resources'][0]['workflows']['main']['jobs']['public']['resolved-image'],
                         {'image': image['build']['image'], 'tag': image['lock']['tag'],
                          'digest': image['lock']['digest']})

    def test_external_dockerfile_ignore_invalidates_hash(self):
        image = copy.deepcopy(read(self.root / 'resources.yaml')['sandbox-images']['default'])
        shutil.copy(self.root / 'sandbox/Dockerfile', self.root / 'Dockerfile')
        image['build']['dockerfile'] = 'Dockerfile'
        before = input_hash(self.root, image)
        (self.root / 'Dockerfile.dockerignore').write_text('ignored-file\n')
        self.assertNotEqual(before, input_hash(self.root, image))

    def test_build_hash_content_and_mode(self):
        image=read(self.root/'resources.yaml')['sandbox-images']['default']
        a=input_hash(self.root,image)
        p=self.root/'sandbox/Dockerfile'
        os.utime(p, (0,0))
        self.assertEqual(a,input_hash(self.root,image))
        p.chmod(0o755)
        self.assertNotEqual(a,input_hash(self.root,image))


if __name__=='__main__': unittest.main()
