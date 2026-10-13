"""Validate/export any benchmark plugin; no benchmark-specific dispatch branches."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from ..catalog import default_registry
from ..core import ContractError, dumps
from ..plugins import read_plugin_request
from .benchmark_stream import BenchmarkStream


def main(argv=None):
    parser = argparse.ArgumentParser(description='Validate a benchmark plugin and export separated memory/evaluation inputs.')
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args(argv)
    try:
        request, context = read_plugin_request(args.config)
        built = default_registry().create(request,role='data_loader',context=context)
        output = args.output_dir.resolve()
        if output.exists():
            raise ContractError('Benchmark output directory already exists')
        for source in getattr(built.instance,'source_paths',()):
            source = Path(source).resolve()
            if source.is_dir() and output.is_relative_to(source):
                raise ContractError('Benchmark output must be outside original data directories')
        class Observer:
            def on_memory(self,memory):
                pass
            def on_report(self,report):
                self.report = report
        observer = Observer()
        stream = BenchmarkStream(loader=built.instance,binding=built.binding,observer=observer)
        output.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='memfolder-benchmark-') as folder:
            temporary = Path(folder)
            with (temporary/'memory.jsonl').open('w',encoding='utf-8') as memory_file, \
                 (temporary/'evaluation.jsonl').open('w',encoding='utf-8') as evaluation_file:
                for sample in stream.samples():
                    memory_file.write(dumps(sample.memory)+'\n')
                    evaluation_file.write(dumps(sample.evaluation)+'\n')
            report = observer.report.to_dict()
            (temporary/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            # Validate before reserving output. Copy only new artifact files.
            output.mkdir(exist_ok=False)
            for source in temporary.iterdir():
                with source.open('rb') as reader,(output/source.name).open('xb') as writer:
                    shutil.copyfileobj(reader,writer)
        print(f"Samples: {report['samples']}; history events: {report['history_events']}; "
              f"memory records: {report['memory_records']}; questions: {report['questions']}")
        return 0
    except (ContractError,OSError,UnicodeError,TypeError) as ex:
        print('Benchmark import failed: '+(str(ex) if isinstance(ex,ContractError) else type(ex).__name__),file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
