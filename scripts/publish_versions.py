"""Register explicitly bumped Resource versions after image locks are committed."""
import os
import subprocess

import yaml

from resources import REPO, require, validate


def run(*args):
    return subprocess.check_output(args, cwd=REPO, text=True).strip()


def main():
    require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'publishing is restricted to main')
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'publishing is restricted to Actions')
    require(not run('git', 'status', '--porcelain'), 'publishing requires a clean checkout')
    manifest, resources = validate(ready=True)
    source = run('git', 'rev-parse', 'HEAD')
    modified = False
    for entry, data in resources:
        history = entry.get('versions', [])
        version = data['resource']['version']
        if history and version == history[-1]['version']:
            continue
        entry['versions'] = [*history, {'version': version, 'commit': source}]
        modified = True
    if not modified:
        print('No new Resource versions')
        return
    run('git', 'fetch', 'origin', 'main')
    require(run('git', 'rev-parse', 'origin/main') == source,
            'main advanced during publication; retry against latest main')
    (REPO / 'resources.yaml').write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
    run('git', 'config', 'user.name', 'github-actions[bot]')
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
    run('git', 'add', '--', 'resources.yaml')
    run('git', 'commit', '-m', 'chore: register resource versions')
    # A normal push rejects a race after the fetch; never rebase immutable records.
    run('git', 'push', 'origin', 'HEAD:main')


if __name__ == '__main__':
    main()
