"""Import a builtin or external memory loader through the same plugin registry."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from ..catalog import default_registry
from ..core import ContractError, dumps
from ..plugins import BuildContext, PluginRequest, read_plugin_request
from .validation import strict_json
from .memory_libraries import save_library
from .contracts import LoadedLibrary


def main(argv=None):
    parser = argparse.ArgumentParser(description='Import memory libraries through builtin or external plugins.')
    parser.add_argument('format', nargs='?', help='Builtin/installed plugin name or module:factory')
    parser.add_argument('path', nargs='?', type=Path)
    parser.add_argument('--config', type=Path, help='Plugin JSON: plugin + parameters; paths relative to this file')
    parser.add_argument('--options', type=Path, help='Shorthand for LoadOptions JSON')
    parser.add_argument('--output-dir', type=Path, help='New directory for library.json, report.json and binding.json')
    parser.add_argument('--collection')
    parser.add_argument('--metadata-path', type=Path)
    parser.add_argument('--list-plugins', action='store_true', help='List names without initializing providers')
    args = parser.parse_args(argv)
    try:
        registry = default_registry()
        if args.list_plugins:
            print('\n'.join(registry.references))
            return 0
        if args.output_dir is None:
            raise ContractError('--output-dir is required')
        if args.config is not None:
            if any(v is not None for v in (args.format,args.path,args.options,args.collection,args.metadata_path)):
                raise ContractError('--config cannot be combined with positional loading options or --options')
            request, context = read_plugin_request(args.config)
        else:
            if args.format is None or args.path is None:
                raise ContractError('Supply FORMAT PATH or --config')
            if args.path.is_dir() and args.output_dir.resolve().is_relative_to(args.path.resolve()):
                raise ContractError('Output directory must be outside the original memory library')
            options = {} if args.options is None else strict_json(args.options.read_text(encoding='utf-8-sig'),'options')
            parameters = {'path':str(args.path),'options':options}
            if args.collection is not None:
                parameters['collection'] = args.collection
            if args.metadata_path is not None:
                parameters['metadata_path'] = str(args.metadata_path)
            request = PluginRequest(plugin=args.format,parameters=parameters)
            context = BuildContext(base_path=Path.cwd())
        built = registry.create(request, role='memory_loader', context=context)
        for source in getattr(built.instance,'source_paths',()):
            source = Path(source).resolve()
            if source.is_dir() and args.output_dir.resolve().is_relative_to(source):
                raise ContractError('Output directory must be outside the original memory library')
        library = built.instance.load()
        if type(library) is not LoadedLibrary:
            raise ContractError('Memory plugin must return LoadedLibrary')
        args.output_dir.mkdir(parents=True,exist_ok=False)
        save_library(library,args.output_dir/'library.json')
        (args.output_dir/'report.json').write_text(dumps(library.report,indent=2)+'\n',encoding='utf-8')
        (args.output_dir/'binding.json').write_text(dumps(built.binding,indent=2)+'\n',encoding='utf-8')
        print(f'Samples: {library.report.samples_loaded}; records: {library.report.records_loaded}; '
              f'edges: {library.report.edges_loaded}; issues: {len(library.report.issues)}')
        return 0
    except (ContractError,OSError,UnicodeError,TypeError) as ex:
        print('Import failed: '+(str(ex) if isinstance(ex,ContractError) else type(ex).__name__),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
