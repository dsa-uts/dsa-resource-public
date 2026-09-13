"""Actions-only image publishing; execute with uv run scripts/build_images.py."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

import yaml
from resources import REPO, image_entries, input_hash, require, validate


def run(*args):
    return subprocess.check_output(args, cwd=REPO, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'publishing is restricted to main')
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'publishing is restricted to Actions')
    manifest, _ = validate()
    source = run('git', 'rev-parse', 'HEAD')
    require(not run('git', 'status', '--porcelain'), 'build requires a clean checkout')
    modified = False
    for index, (key, root, image) in enumerate(image_entries(REPO, manifest)):
        fingerprint = input_hash(root, image)
        lock = image['lock']
        if not args.force and lock and lock['input-hash'] == fingerprint:
            print(f'{key}: unchanged, keeping {lock["digest"]}', flush=True)
            continue
        build = image['build']
        tag = f'{source}-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}-{index}'
        with tempfile.TemporaryDirectory() as temp:
            metadata = Path(temp) / 'metadata.json'
            subprocess.run(['docker', 'buildx', 'build', '--push', '--pull', '--no-cache',
                            '--platform', ','.join(build['platforms']),
                            '--file', str(root / build['dockerfile']),
                            '--tag', build['image'] + ':' + tag,
                            '--metadata-file', str(metadata), str(root / build['context'])], check=True)
            digest = json.loads(metadata.read_text())['containerimage.digest']
        image['lock'] = {'tag': tag, 'digest': digest, 'input-hash': fingerprint,
                         'source-ref': source, 'actions-run-id': os.environ['GITHUB_RUN_ID']}
        modified = True
    if not modified:
        return
    # Do not rebase generated results onto another source commit. All main pushes
    # enqueue an Actions Run, which checks out current main after acquiring the lock.
    run('git', 'fetch', 'origin', 'main')
    require(run('git', 'rev-parse', 'origin/main') == source,
            'main advanced during build; discard these results and let the queued run rebuild')
    (REPO / 'resources.yaml').write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    validate(ready=True)
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    run('git', 'add', '--', 'resources.yaml')
    run('git', 'commit', '-m', 'chore: lock sandbox image digests')
    # Normal fast-forward push also rejects races after the fetch above.
    run('git', 'push', 'origin', 'HEAD:main')


if __name__ == '__main__':
    main()
