"""Validate and resolve Resource manifests. Run with uv run scripts/resources.py."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

import jsonschema
import yaml

REPO = Path(__file__).resolve().parents[1]


class Invalid(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_map(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise Invalid(f'duplicate or non-string YAML key: {key!r}')
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor('tag:yaml.org,2002:map', unique_map)


def read(path):
    return yaml.load(path.read_text(), Loader=UniqueLoader)


def require(condition, message):
    if not condition:
        raise Invalid(message)


def relative(value, dot=False):
    require(isinstance(value, str) and bool(value), 'empty path')
    if dot and value == '.':
        return
    require(not value.startswith('/') and not any(c in value for c in '\\\0:'), f'unsafe path: {value}')
    require(all(p not in ('', '.', '..') for p in value.split('/')), f'unclean path: {value}')


def file_path(root, value, directory=False, dot=False):
    relative(value, dot)
    current = root
    for part in value.split('/'):
        current = current / part
        require(not current.is_symlink(), f'symlink forbidden: {current}')
    require(current.is_dir() if directory else current.is_file(), f'missing or wrong file type: {current}')
    require(current.resolve().is_relative_to(root.resolve()), f'path escapes root: {value}')
    if not directory:
        require(current.stat().st_nlink == 1, f'hardlink forbidden: {current}')
    return current


def schema_check(data, name):
    schema = json.loads((REPO / f'schemas/{name}.schema.json').read_text())
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data), key=lambda e: str(e.path))
    if errors:
        raise Invalid(f'{name} {list(errors[0].path)}: {errors[0].message}')


def input_hash(root, image):
    """Hash build declaration and every context entry (including ignored files).

    Files outside the context are forbidden except the explicitly named Dockerfile.
    Names, executable modes, bytes and empty directories participate; mtimes do not.
    """
    build = image['build']
    context = file_path(root, build['context'], directory=True, dot=True)
    dockerfile = file_path(root, build['dockerfile'])
    digest = hashlib.sha256()
    def add(value):
        digest.update(len(value).to_bytes(8, 'big'))
        digest.update(value)
    add(json.dumps(build, sort_keys=True, separators=(',', ':')).encode())
    entries = sorted(context.rglob('*'))
    require(not any('.git' in p.relative_to(context).parts or p.name in ('resource.yaml', 'resources.yaml') for p in entries),
            'build context must exclude .git and manifests; use a dedicated directory')
    for path in entries:
        require(not path.is_symlink(), f'build symlink forbidden: {path}')
        mode = path.stat().st_mode
        require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), f'unsupported build input: {path}')
        add(path.relative_to(context).as_posix().encode())
        add(b'd' if path.is_dir() else b'x' if mode & 0o111 else b'f')
        if path.is_file():
            require(path.stat().st_nlink == 1, f'build hardlink forbidden: {path}')
            add(path.read_bytes())
    add(dockerfile.read_bytes())
    # Dockerfile-specific ignore files can live outside the context as well.
    ignore = build['dockerfile'] + '.dockerignore'
    add(file_path(root, ignore).read_bytes() if (root / ignore).exists() or (root / ignore).is_symlink() else b'')
    # A pinned single-stage base keeps the build contract deliberately small.
    instructions = [line.strip() for line in dockerfile.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#')]
    bases = [line for line in instructions if line.upper().startswith('FROM ')]
    require(len(bases) == 1 and re.fullmatch(r'FROM [a-z0-9./_-]+:[A-Za-z0-9_.-]+@sha256:[a-f0-9]{64}', bases[0]), 'Dockerfile requires one tag+digest pinned FROM')
    require(not any(line.upper().startswith('ADD ') for line in instructions), 'ADD is not supported; use local COPY')
    require(not any(line.lstrip().lower().startswith('# syntax=') for line in dockerfile.read_text().splitlines()), 'external Dockerfile frontends are not supported')
    return 'sha256:' + digest.hexdigest()


def image_entries(root, manifest):
    for key, image in manifest['sandbox-images'].items():
        yield 'shared/' + key, root, image


def check_history(root, manifest, base):
    """Authors may edit resources, but only the publisher may add version records."""
    require(re.fullmatch(r'[a-f0-9]{40}', base) is not None, 'history base must be a full commit SHA')
    previous = yaml.load(subprocess.check_output(
        ['git', 'show', f'{base}:resources.yaml'], cwd=root, text=True), Loader=UniqueLoader)
    histories = {entry['id']: entry.get('versions', []) for entry in previous['resources']}
    for entry in manifest['resources']:
        require(entry.get('versions', []) == histories.get(entry['id'], []),
                f'{entry["id"]}: versions are bot-managed; do not edit registered history')


def validate(root=REPO, ready=False):
    root = Path(root).resolve()
    manifest = read(file_path(root, 'resources.yaml'))
    schema_check(manifest, 'resources')
    resources = []
    ids, paths = set(), set()
    for entry in manifest['resources']:
        require(entry['id'] not in ids and entry['path'] not in paths, 'duplicate Resource ID/path')
        ids.add(entry['id']); paths.add(entry['path'])
        source = file_path(root, entry['path'])
        require(source.name == 'resource.yaml' and source.parent != root, 'Resource must have its own directory/resource.yaml')
        data = read(source)
        schema_check(data, 'resource')
        require(data['resource']['id'] == entry['id'], 'Resource ID mismatch')
        version = data['resource']['version']
        require(type(version) is int, 'Resource version must be an integer')
        latest = 0
        for record in entry.get('versions', []):
            require(type(record['version']) is int and record['version'] > latest,
                    f'{entry["id"]}: registered versions must be strictly increasing integers')
            latest = record['version']
        require(version >= latest, f'{entry["id"]}: version must not decrease below registered version {latest}')
        images = manifest['sandbox-images']
        for workflow in data['workflows'].values():
            if 'description-path' in workflow:
                file_path(source.parent, workflow['description-path'])
            destinations = set()
            for preset in workflow.get('presets', {}).get('files', []):
                file_path(source.parent, preset['source'])
                relative(preset['path'])
                require(preset['path'] not in destinations, 'duplicate Preset path')
                destinations.add(preset['path'])
            jobs = workflow['jobs']
            for jid, job in jobs.items():
                require(job['sandbox-image'] in images, f'unknown image: {job["sandbox-image"]}')
                wd = job.get('working-directory', '/workspace')
                if wd != '/workspace': relative(wd[len('/workspace/'):])
                deps = job.get('depends', [])
                for dep in deps:
                    require(dep in jobs and dep != jid, f'invalid dependency: {dep}')
                    require(job.get('visibility', 'private') != 'public' or jobs[dep].get('visibility', 'private') == 'public', 'public Job depends on private Job')
                artifacts = job.get('artifacts', {})
                for kind in ['inputs', 'outputs']:
                    seen_names, seen_paths = set(), set()
                    for artifact in artifacts.get(kind, []):
                        relative(artifact['path'])
                        require(artifact['path'] not in seen_paths, 'duplicate Artifact path')
                        seen_paths.add(artifact['path'])
                        if kind == 'outputs':
                            require(artifact['name'] not in seen_names, 'duplicate Artifact name')
                            seen_names.add(artifact['name'])
                        else:
                            producer = artifact['from-job']
                            require(producer in deps, 'Artifact producer must be a direct dependency')
                            outputs = jobs[producer].get('artifacts', {}).get('outputs', [])
                            require(any(a['name'] == artifact['name'] for a in outputs), 'unknown Artifact output')
                for step in job['steps']:
                    require(bool(step['run'].strip()) and '\0' not in step['run'], 'invalid run script')
                    for stream in [step.get('stdin', {}), *[step.get('expected', {}).get(k, {}) for k in ['stdout', 'stderr']]]:
                        if 'path' in stream: file_path(source.parent, stream['path'])
            visited, visiting = set(), set()
            def visit(jid):
                require(jid not in visiting, 'dependency cycle')
                if jid in visited: return
                visiting.add(jid)
                for dep in jobs[jid].get('depends', []): visit(dep)
                visiting.remove(jid); visited.add(jid)
            for jid in jobs: visit(jid)
        resources.append((entry, data))
    for key, base, image in image_entries(root, manifest):
        current = input_hash(base, image)
        if ready:
            require(image['lock'] is not None, f'{key}: image has not been built')
            require(image['lock']['input-hash'] == current, f'{key}: stale image lock')
    return manifest, resources


def expand(root=REPO, ready=True):
    manifest, resources = validate(root, ready=ready)
    result = {'resources': []}
    for entry, original in resources:
        data = copy.deepcopy(original)
        images = manifest['sandbox-images']
        for workflow in data['workflows'].values():
            for job in workflow['jobs'].values():
                image = images[job['sandbox-image']]
                lock = image['lock']
                job['resolved-image'] = {'image': image['build']['image'], 'tag': lock['tag'] if lock else None, 'digest': lock['digest'] if lock else None}
        result['resources'].append({'path': entry['path'], **data})
    return yaml.safe_dump(result, allow_unicode=True, sort_keys=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'expand'])
    parser.add_argument('--root', type=Path, default=REPO)
    parser.add_argument('--ready', action='store_true', help='require up-to-date image locks for import')
    parser.add_argument('--allow-unbuilt', action='store_true', help='expand draft configuration for review only')
    parser.add_argument('--history-base', help='reject manual history changes relative to this full commit SHA')
    args = parser.parse_args()
    try:
        if args.command == 'expand':
            print(expand(args.root, ready=not args.allow_unbuilt), end='')
        else:
            manifest, _ = validate(args.root, ready=args.ready)
            if args.history_base:
                check_history(args.root, manifest, args.history_base)
            print('Resource validation passed' + (' (import-ready)' if args.ready else ' (source only)'))
    except (Invalid, OSError, yaml.YAMLError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
