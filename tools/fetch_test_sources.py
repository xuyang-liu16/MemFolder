"""Download pinned test references and verify SHA256 before storing any source.

This optional step enables native-reader tests in a standalone checkout. It does
not install SDKs, download models, or run QA. Cached files are also verified.
"""
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def references():
    wrapper = json.loads((ROOT / 'docs/WRAPPER_SOURCES.json').read_text(encoding='utf-8'))
    for framework, metadata in wrapper['official_sources'].items():
        for item in metadata['sources']:
            yield ROOT / 'build/upstream' / framework / item['path'], item['url'], item['sha256']
    benchmark = json.loads((ROOT / 'docs/BENCHMARK_SOURCES.json').read_text(encoding='utf-8'))
    for metadata in benchmark['sources']:
        for item in metadata['files']:
            if not item['path'].endswith('.py'):
                continue
            url = ('https://raw.githubusercontent.com/' + metadata['repository'] + '/' +
                   metadata['revision'] + '/' + item['path'])
            yield ROOT / 'build/upstream/benchmarks' / metadata['dataset'] / item['path'], url, item['sha256']


def main():
    count = downloaded = 0
    root = (ROOT / 'build/upstream').resolve()
    for path, url, expected in references():
        if not path.resolve().is_relative_to(root):
            raise ValueError('Reference escaped the test-source directory')
        if path.exists():
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Existing pinned reference changed: ' + str(path.relative_to(ROOT)))
        else:
            request = Request(url, headers={'User-Agent': 'MemFolder-source-verification'})
            with urlopen(request, timeout=60) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024 or sha256(data).hexdigest() != expected:
                raise ValueError('Reference size or SHA256 mismatch: ' + str(path.relative_to(ROOT)))
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + '.partial')
            temporary.write_bytes(data)
            temporary.replace(path)
            downloaded += 1
        count += 1
    print(json.dumps({'status': 'verified', 'references': count, 'downloaded': downloaded}))


if __name__ == '__main__':
    main()
