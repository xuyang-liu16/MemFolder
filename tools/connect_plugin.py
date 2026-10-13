"""Validate a plugin and connect it to a configuration without editing the catalog."""
import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def bootstrap():
    if 'memfolder' not in sys.modules:
        spec = importlib.util.spec_from_file_location('memfolder', ROOT / 'src/__init__.py',
            submodule_search_locations=[str(ROOT / 'src')])
        module = importlib.util.module_from_spec(spec)
        sys.modules['memfolder'] = module
        spec.loader.exec_module(module)


def read_json(path):
    from memfolder.loading.validation import strict_json
    path = Path(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError('Configuration must be a file of at most 1 MiB')
    value = strict_json(path.read_text(encoding='utf-8-sig'), 'integration.config')
    if type(value) is not dict:
        raise ValueError('Configuration must be a JSON object')
    return value


def output_path(path):
    path = Path(path).resolve()
    if path.is_relative_to(ROOT):
        raise ValueError('Choose an output outside the source checkout')
    return path


def write_json(path, value, *, replace=False):
    path = output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise FileExistsError('Output already exists; select another output or use --replace')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                        prefix='.memfolder-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write('\n')
        if replace:
            temporary.replace(path)
        else:
            os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def replace_slot(config, pointer, request):
    if not pointer.startswith('/') or pointer == '/':
        raise ValueError('Slot must be a JSON pointer, e.g. /dataset or /compression/planner')
    keys = pointer[1:].split('/')
    if any(not key or '~' in key.replace('~0', '').replace('~1', '') for key in keys):
        raise ValueError('Invalid JSON pointer')
    keys = [key.replace('~1', '/').replace('~0', '~') for key in keys]
    result = deepcopy(config)
    def index(key):
        if not key.isdecimal() or str(int(key)) != key:
            raise ValueError('Array slots require nonnegative canonical indices')
        return int(key)
    parent = result
    for key in keys[:-1]:
        parent = parent[index(key)] if type(parent) is list else parent[key]
    if type(parent) is list:
        position = len(parent) if keys[-1] == '-' else index(keys[-1])
        if position == len(parent):
            parent.append(request)
        else:
            parent[position] = request
    elif type(parent) is dict:
        parent[keys[-1]] = request
    else:
        raise ValueError('Slot parent must be an object or array')
    return result


def connect(request, role, output, *, configuration=None, slot=None, available=(), replace=False):
    bootstrap()
    from memfolder.catalog import default_registry
    from memfolder.plugins import BuildContext, PluginRequest
    from memfolder.assembly import assemble
    from memfolder.experiment import assemble_experiment
    from memfolder.core import validate_composition
    output = output_path(output)
    base = Path(configuration).resolve().parent if configuration else output.parent
    if configuration and output.parent != base:
        raise ValueError('Keep the output beside the input configuration to preserve relative asset paths')
    registry = default_registry()
    built = registry.create(PluginRequest.from_mapping(request), role=role,
        context=BuildContext(base_path=base, registry=registry, available=tuple(available)),
        available=tuple(available))
    result = request
    if configuration:
        if not slot:
            raise ValueError('--slot is required with --config')
        result = replace_slot(read_json(configuration), slot, request)
        if 'compression' in result:
            assembled = assemble_experiment(result, registry=registry, base_path=base, available=tuple(available))
            engine, mode = assembled.compression.engine, assembled.settings['mode']
        else:
            engine = assemble(result, registry=registry, base_path=base, available=tuple(available)).engine
            mode = 'once'
        validate_composition(engine.planner.spec, (engine.operator.spec,), mode=mode, available=tuple(available))
    elif slot:
        raise ValueError('--slot requires --config')
    write_json(output, result, replace=replace)
    return built


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=
        'Install a contributor package first (pip install -e PATH). Plugins may use installed names '
        'or module:factory. Output configurations and parameters stay outside the checkout.')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--plugin', help='Installed name or importable module:factory')
    source.add_argument('--request', type=Path, help='Plugin configuration generated by prepare_assets.py')
    parser.add_argument('--role', required=True, help='data_loader, memory_loader, planner, operator, wrapper, service, ...')
    parser.add_argument('--parameters', type=Path, help='JSON object of parameters for --plugin')
    parser.add_argument('--config', type=Path, help='Existing experiment or compression configuration')
    parser.add_argument('--slot', help='Component JSON pointer; use /- to append to a component list')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--available', action='append', default=[], help='Explicit capability; repeat as needed')
    parser.add_argument('--replace', action='store_true', help='Permit replacing the selected output file')
    args = parser.parse_args(argv)
    try:
        bootstrap()
        if args.request and args.parameters:
            raise ValueError('--parameters only applies to --plugin')
        request = read_json(args.request) if args.request else {'plugin': args.plugin,
            'parameters': read_json(args.parameters) if args.parameters else {}}
        # Parameters in a standalone request are resolved alongside that request.
        if args.request and not args.config and args.request.resolve().parent != args.output.resolve().parent:
            raise ValueError('Keep the copied request beside the original to preserve relative paths')
        built = connect(request, args.role, args.output, configuration=args.config, slot=args.slot,
                        available=args.available, replace=args.replace)
        print(json.dumps({'output': str(args.output.resolve()), 'plugin_id': built.instance.spec.plugin_id,
                          'role': args.role, 'status': 'configuration_validated'}))
        return 0
    except Exception as error:
        from memfolder.core import ContractError
        message = str(error) if isinstance(error, (ContractError, ValueError, FileExistsError)) else type(error).__name__
        print('Plugin connection failed: ' + message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
