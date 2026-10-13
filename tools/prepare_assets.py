"""Download benchmark data, memory exports or model weights and emit loader/service config."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

from connect_plugin import bootstrap, output_path, read_json, write_json


PRESETS = {
    'locomo': ('locomo-dataset', 'main',
        'https://raw.githubusercontent.com/snap-research/locomo/{revision}/data/locomo10.json'),
    'longmemeval': ('longmemeval-dataset', 'main',
        'https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/{revision}/longmemeval_{variant}.json'),
    'personamem': ('personamem-dataset', 'main',
        'https://huggingface.co/datasets/bowen-upenn/PersonaMem/resolve/{revision}/questions_{variant}.csv'),
    'm3': ('m3-dataset', 'master',
        'https://raw.githubusercontent.com/ByteDance-Seed/m3-agent/{revision}/data/annotations/{variant}.json'),
}


def download(url, directory, *, expected_sha256=None, max_bytes=8 * 1024**3, token=None):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Source must be an HTTP(S) URL without embedded credentials')
    name = Path(urllib.parse.unquote(parsed.path)).name
    if not name or name in ('.', '..') or any(c in name for c in '\\/:'):
        raise ValueError('Source URL needs a safe filename')
    if expected_sha256 and not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256):
        raise ValueError('--sha256 must contain 64 hexadecimal characters')
    destination = directory / name
    if destination.exists():
        if not expected_sha256:
            raise FileExistsError('Asset already exists; supply its --sha256 for verified reuse or choose a new directory')
        if sha256_file(destination) == expected_sha256.lower():
            return destination
        raise ValueError('Existing asset checksum mismatch')
    headers = {'User-Agent': 'MemFolder-assets/1', 'Accept-Encoding': 'identity'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    # urllib follows redirects; never forward credentials to a different host.
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, *args):
            redirected = super().redirect_request(request, *args)
            if redirected is not None and urllib.parse.urlsplit(redirected.full_url).netloc != parsed.netloc:
                redirected.remove_header('Authorization')
            return redirected
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with urllib.request.build_opener(Redirect()).open(urllib.request.Request(url, headers=headers), timeout=60) as source, \
                tempfile.NamedTemporaryFile(dir=directory, prefix='.download-', delete=False) as target:
            temporary = Path(target.name)
            length = source.headers.get('Content-Length')
            if length is not None and int(length) > max_bytes:
                raise ValueError('Download exceeds --max-bytes')
            total, digest = 0, sha256()
            while block := source.read(1024 * 1024):
                total += len(block)
                if total > max_bytes:
                    raise ValueError('Download exceeds --max-bytes')
                target.write(block)
                digest.update(block)
            if not total or length is not None and total != int(length):
                raise ValueError('Empty or incomplete download')
            if expected_sha256 and digest.hexdigest() != expected_sha256.lower():
                raise ValueError('Downloaded asset checksum mismatch')
        os.link(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sha256_file(path):
    digest = sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def extract(path, directory, *, max_bytes):
    output = directory / 'extracted'
    if output.exists():
        raise FileExistsError('Extracted output already exists')
    with tempfile.TemporaryDirectory(dir=directory, prefix='.extract-') as name:
        staging = Path(name)
        total = 0
        def destination(member, size):
            nonlocal total
            if '\\' in member or ':' in member:
                raise ValueError('Unsafe archive path')
            target = (staging / member).resolve()
            if not target.is_relative_to(staging) or target == staging:
                raise ValueError('Archive member escapes extraction directory')
            total += size
            if total > max_bytes:
                raise ValueError('Extracted files exceed --max-bytes')
            return target
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    if (member.external_attr >> 16) & 0o170000 not in (0, 0o100000):
                        raise ValueError('Archive links/devices are unsupported')
                    target = destination(member.filename, member.file_size)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open('xb') as stream:
                        shutil.copyfileobj(source, stream)
        else:
            with tarfile.open(path) as archive:
                for member in archive:
                    if member.isdir():
                        continue
                    if not member.isfile():
                        raise ValueError('Archive links/devices are unsupported')
                    target = destination(member.name, member.size)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, target.open('xb') as stream:
                        shutil.copyfileobj(source, stream)
        staging.rename(output)
    return output


def validate_input(built, role):
    if role == 'memory_loader':
        library = built.instance.load()
        if not library.inputs:
            raise ValueError('Memory source contains no samples')
    elif role == 'data_loader':
        stream = iter(built.instance.samples())
        try:
            from memfolder.core import DatasetSample
            if type(next(stream, None)) is not DatasetSample:
                raise ValueError('Benchmark source must yield DatasetSample')
        finally:
            if callable(getattr(stream, 'close', None)):
                stream.close()


def prepare(args):
    bootstrap()
    directory = output_path(args.output_dir)
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError('Choose a new or empty output directory')
    if getattr(args, 'max_bytes', 1) <= 0:
        raise ValueError('--max-bytes must be positive')
    if args.kind == 'dataset' and args.benchmark == 'm3' and (not args.memory_dir or not args.memory_dir.is_dir()):
        raise ValueError('M3 requires --memory-dir containing the native video memory graphs')
    parameters = read_json(args.parameters) if args.parameters else {}
    directory.mkdir(parents=True, exist_ok=True)
    role = 'service' if args.kind == 'model' else 'memory_loader' if args.kind == 'memory' else 'data_loader'
    asset_dir = directory / 'assets'
    if args.kind == 'model':
        from memfolder.services import LLMLingua2Service
        if not args.plugin and args.repo_id != LLMLingua2Service.model_name:
            raise ValueError('A different model requires its compatible --plugin service')
        os.environ.setdefault('HF_HOME', str(directory / '.cache/huggingface'))
        os.environ.setdefault('HF_XET_CACHE', str(directory / '.cache/xet'))
        try:
            from huggingface_hub import HfApi, snapshot_download
        except ImportError:
            raise ValueError('Install huggingface_hub to download model weights') from None
        revision = args.revision or (LLMLingua2Service.revision
            if args.repo_id == LLMLingua2Service.model_name else 'main')
        info = HfApi().model_info(args.repo_id, revision=revision)
        checkpoint = snapshot_download(repo_id=args.repo_id, revision=info.sha,
            local_dir=asset_dir, cache_dir=directory / '.cache', max_workers=args.workers)
        plugin = args.plugin or 'llmlingua2-service'
        parameters[args.model_parameter] = str(Path(checkpoint).resolve())
        if plugin == 'llmlingua2-service' or args.revision_parameter:
            parameters[args.revision_parameter or 'revision'] = info.sha
    else:
        token = os.environ.get(args.token_env) if args.token_env else None
        if args.token_env and not token:
            raise ValueError('The selected token environment variable is empty')
        if args.kind == 'dataset':
            plugin, revision, url = PRESETS[args.benchmark]
            variants = {'longmemeval': {'s': 's_cleaned', 'm': 'm_cleaned', 'oracle': 'oracle'},
                        'personamem': {'32k': '32k', '128k': '128k', '1M': '1M'},
                        'm3': {'robot': 'robot', 'web': 'web'}, 'locomo': {'default': 'default'}}
            chosen = args.variant or next(iter(variants[args.benchmark]))
            if chosen not in variants[args.benchmark]:
                raise ValueError('Unsupported variant for the selected benchmark')
            revision = args.revision or revision
            url = url.format(revision=urllib.parse.quote(revision, safe=''), variant=variants[args.benchmark][chosen])
            path = download(url, asset_dir, max_bytes=args.max_bytes, token=token)
            if args.benchmark in ('locomo', 'longmemeval'):
                parameters.setdefault('utc_offset_minutes', args.utc_offset_minutes)
            if args.benchmark == 'locomo':
                parameters.setdefault('evidence_policy', 'preserve_unknown')
            if args.benchmark == 'personamem':
                contexts = download(url.replace('questions_', 'shared_contexts_').replace('.csv', '.jsonl'),
                                    asset_dir, max_bytes=args.max_bytes, token=token)
                parameters['contexts_path'] = str(contexts)
            if args.benchmark == 'm3':
                if not args.memory_dir:
                    raise ValueError('M3 requires --memory-dir containing the native video memory graphs')
                banks = {}
                graph_dir = args.memory_dir.resolve()
                graphs = {}
                for graph in graph_dir.rglob('*.pkl'):
                    graphs.setdefault(graph.stem, []).append(graph)
                for video in json.loads(path.read_text(encoding='utf-8')):
                    if parameters.get('sample_ids') and video not in parameters['sample_ids']:
                        continue
                    candidates = graphs.get(video, [])
                    if len(candidates) != 1:
                        raise ValueError('Each M3 video needs exactly one matching <video_id>.pkl')
                    banks[video] = {'plugin': 'm3', 'parameters': {'path': str(candidates[0]),
                        'options': {'dataset_id': 'm3.' + chosen, 'order_by': 'numeric_native_id'}}}
                parameters.update({'variant': chosen, 'memory_loaders': banks})
        else:
            plugin = args.plugin
            path = download(args.url, asset_dir, expected_sha256=args.sha256,
                            max_bytes=args.max_bytes, token=token)
            if args.extract:
                if not args.asset_path:
                    raise ValueError('--asset-path is required with --extract')
                extracted = extract(path, asset_dir, max_bytes=args.max_bytes)
                path = (extracted / args.asset_path).resolve()
                if not path.is_relative_to(extracted):
                    raise ValueError('--asset-path must stay inside the archive')
                if not path.exists():
                    raise ValueError('--asset-path was not found in the archive')
        parameters['path'] = str(path.resolve())
    from memfolder.catalog import default_registry
    from memfolder.plugins import BuildContext, PluginRequest
    request = {'plugin': plugin, 'parameters': parameters}
    registry = default_registry()
    built = registry.create(PluginRequest.from_mapping(request), role=role,
                            context=BuildContext(base_path=directory, registry=registry))
    validate_input(built, role)
    output = directory / ('service.json' if role == 'service' else 'loader.json')
    write_json(output, request)
    return output, role


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=
        'Pass the generated loader/service request to connect_plugin.py --request. '
        'Input validation reads a benchmark sample or the memory bank; it never calls a model or evaluates QA.')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--output-dir', type=Path, required=True, help='New/empty directory outside the checkout')
    common.add_argument('--parameters', type=Path, help='Additional plugin parameters as a JSON object')
    subparsers = parser.add_subparsers(dest='kind', required=True)
    dataset = subparsers.add_parser('dataset', parents=[common], help='Download official benchmark release files',
        description='Download a builtin release and emit its loader config. LoCoMo preserves unresolved evidence '
                    'IDs in annotations; override evidence_policy using --parameters if strict rejection is desired.')
    dataset.add_argument('benchmark', choices=PRESETS)
    dataset.add_argument('--variant', help='LongMemEval: s/m/oracle; PersonaMem: 32k/128k/1M; M3: robot/web')
    dataset.add_argument('--revision', help='Upstream commit/tag (default: the official release branch)')
    dataset.add_argument('--utc-offset-minutes', type=int, default=0,
                         help='Explicit offset for naive dataset timestamps (default: UTC)')
    dataset.add_argument('--memory-dir', type=Path, help='M3 native graphs, one <video_id>.pkl per video')
    memory = subparsers.add_parser('memory', parents=[common], help='Download an exported memory bank')
    memory.add_argument('url')
    memory.add_argument('--plugin', required=True, help='mem0, memos, m3, canonical, or an installed memory loader')
    memory.add_argument('--sha256', help='Expected SHA256 of the download')
    memory.add_argument('--extract', action='store_true', help='Extract a ZIP or TAR archive')
    memory.add_argument('--asset-path', help='File or directory inside the extracted archive, e.g. bank/storage')
    for command in (dataset, memory):
        command.add_argument('--max-bytes', type=int, default=8 * 1024**3, help='Download/extraction size limit')
        command.add_argument('--token-env', help='Environment variable containing the private source token')
    model = subparsers.add_parser('model', parents=[common], help='Download a pinned Hugging Face model snapshot')
    bootstrap()
    from memfolder.services import LLMLingua2Service
    model.add_argument('repo_id', nargs='?', default=LLMLingua2Service.model_name)
    model.add_argument('--revision', help='Commit/tag; LLMLingua-2 defaults to the framework-pinned commit')
    model.add_argument('--plugin', help='Compatible local-weight service plugin (default for LLMLingua-2: llmlingua2-service)')
    model.add_argument('--model-parameter', default='model_name', help='Plugin parameter receiving the local model directory')
    model.add_argument('--revision-parameter', help='Custom plugin parameter receiving the resolved model revision')
    model.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.kind == 'model' and args.workers <= 0:
            raise ValueError('--workers must be positive')
        output, role = prepare(args)
        print(json.dumps({'output': str(output), 'role': role, 'status': 'ready'}))
        return 0
    except Exception as error:
        from memfolder.core import ContractError
        message = str(error) if isinstance(error, (ContractError, ValueError, FileExistsError)) else type(error).__name__
        print('Asset preparation failed: ' + message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
