"""Real extension boundaries: lazy loading, validation, CLI and independent providers."""
from dataclasses import replace
from hashlib import sha256
from importlib.metadata import EntryPoint
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from memfolder.catalog import default_registry
from memfolder.core import ContractError, FrozenMap, PluginSpec, fingerprint, dumps, loads
from memfolder.loading import load_library, load_mem0
from memfolder.plugins import BuildContext, PluginRegistry, PluginRequest, read_plugin_request

ROOT = Path(__file__).resolve().parents[1]


class SimplePlugin:
    spec = PluginSpec(plugin_id='lab.loader',role='data_loader',provides=('benchmark.samples',))
    def samples(self):
        return iter(())


def build_simple(parameters,*,context):
    return SimplePlugin()
build_simple.spec = SimplePlugin.spec


class PluginTests(unittest.TestCase):
    def test_callable_factory_objects_have_inspectable_implementation_binding(self):
        class Factory:
            spec=SimplePlugin.spec
            def __call__(self,parameters,*,context):return SimplePlugin()
        registry=PluginRegistry();registry.register('object',Factory())
        built=registry.create(PluginRequest(plugin='object'),role='data_loader')
        self.assertTrue(built.binding.implementation_revision.startswith('sha256:'))

    def test_registration_and_discovery_do_not_import_unselected_providers(self):
        registry = PluginRegistry()
        registry.register('missing','not_installed_optional_backend:build')
        registry.discover(entry_points=[EntryPoint(name='lab.example',value='other_missing:build',group='memfolder.plugins')])
        self.assertEqual(registry.references,('lab.example','missing'))
        self.assertNotIn('not_installed_optional_backend',sys.modules)
        registry.register('ready',build_simple)
        built=registry.create(PluginRequest(plugin='ready'),role='data_loader')
        self.assertEqual(built.instance.spec.plugin_id,'lab.loader')
        with self.assertRaises(ContractError):
            registry.create(PluginRequest(plugin='missing'),role='data_loader')

    def test_duplicates_fail_transactionally_without_override(self):
        registry=PluginRegistry()
        registry.register('existing',build_simple)
        with self.assertRaises(ContractError):
            registry.register('existing',build_simple)
        with self.assertRaises(ContractError):
            registry.discover(entry_points=[EntryPoint(name='new',value='a:build',group='memfolder.plugins'),
                EntryPoint(name='existing',value='b:build',group='memfolder.plugins')])
        self.assertEqual(registry.references,('existing',))
        with self.assertRaises(ContractError):
            registry.discover(entry_points=[EntryPoint(name='double',value='a:build',group='memfolder.plugins')]*2)

    def test_role_version_and_capabilities_fail_before_factory_execution(self):
        calls=[]
        def factory(parameters,*,context):
            calls.append(1)
            return SimplePlugin()
        registry=PluginRegistry()
        registry.register('test',factory)
        for spec,role in [(SimplePlugin.spec,'memory_loader'),
                          (replace(SimplePlugin.spec,api_version=2),'data_loader'),
                          (replace(SimplePlugin.spec,requires=('missing.service',)),'data_loader')]:
            factory.spec=spec
            with self.assertRaises(ContractError):
                registry.create(PluginRequest(plugin='test'),role=role)
        self.assertEqual(calls,[])

    def test_factory_must_advertise_spec_and_result_must_match_it(self):
        registry=PluginRegistry()
        def factory(parameters,*,context):
            return SimplePlugin()
        registry.register('factory',factory)
        with self.assertRaises(ContractError):
            registry.create(PluginRequest(plugin='factory'),role='data_loader')
        factory.spec=replace(SimplePlugin.spec,plugin_id='changed')
        with self.assertRaisesRegex(ContractError,'changed its advertised spec'):
            registry.create(PluginRequest(plugin='factory'),role='data_loader')
        factory.spec=SimplePlugin.spec
        def wrong(parameters,*,context):
            return type('NoMethod',(),{'spec':SimplePlugin.spec})()
        wrong.spec=SimplePlugin.spec
        registry.register('wrong',wrong)
        with self.assertRaisesRegex(ContractError,'role method'):
            registry.create(PluginRequest(plugin='wrong'),role='data_loader')

    def test_explicit_target_and_parameter_binding_are_detached_and_content_free(self):
        parameters={'token':'CONFIG_SECRET','nested':{'a':[1,2]}}
        request=PluginRequest(plugin='test_plugins:build_simple',parameters=parameters)
        parameters['nested']['a'].append(3)
        built=PluginRegistry().create(request,role='data_loader')
        self.assertEqual(request.parameters['nested']['a'],(1,2))
        self.assertEqual(built.binding.parameters_fingerprint,fingerprint(request.parameters))
        self.assertTrue(built.binding.implementation_revision.startswith('sha256:'))
        self.assertNotIn('CONFIG_SECRET',dumps(built.binding))
        self.assertEqual(loads(dumps(built.binding)),built.binding)

    def test_config_unknown_fields_null_parameters_duplicate_fields_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            for raw in ['{"plugin":"x","unknown":1}','{"plugin":"x","parameters":null}',
                        '{"plugin":"x","plugin":"y"}','{"plugin":"x","parameters":{"n":NaN}}']:
                path.write_text(raw)
                with self.assertRaises(ContractError):
                    read_plugin_request(path)
            path.write_text('{"plugin":"x","parameters":{"path":"data.json"}}')
            request,context=read_plugin_request(path)
            self.assertEqual(context.path(request.parameters['path']),Path(folder)/'data.json')

    def test_invalid_targets_unknown_names_and_factory_errors_are_explicit_and_sanitized(self):
        registry=PluginRegistry()
        for reference in ('unknown','invalid:too:many','bad-module:build','test_plugins:absent'):
            with self.assertRaises(ContractError):
                registry.create(PluginRequest(plugin=reference),role='data_loader')
        def broken(parameters,*,context):
            raise ContractError('MEMORY_AND_CONFIG_SECRET')
        broken.spec=SimplePlugin.spec
        registry.register('broken',broken)
        with self.assertRaises(ContractError) as caught:
            registry.create(PluginRequest(plugin='broken'),role='data_loader')
        self.assertNotIn('MEMORY_AND_CONFIG_SECRET',str(caught.exception))

    def test_builtin_memory_plugin_preserves_existing_import_semantics_and_unknown_options_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'memory.json'
            path.write_text(json.dumps([{'id':'1','memory':'original','user_id':'a'}]))
            registry=default_registry(discover=False)
            built=registry.create(PluginRequest(plugin='mem0',parameters={'path':str(path)}),role='memory_loader')
            self.assertEqual(built.instance.load(),load_mem0(path))
            with self.assertRaises(ContractError):
                registry.create(PluginRequest(plugin='mem0',parameters={'path':str(path),'options':{'typo':1}}),role='memory_loader')

    def test_cli_config_loading_and_legacy_shorthand_use_same_output(self):
        import os
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            path=root/'memory.json'
            path.write_text(json.dumps([{'id':'1','memory':'PRIVATE_MEMORY_TEXT','user_id':'a'}]))
            config=root/'config.json'
            config.write_text(json.dumps({'plugin':'mem0','parameters':{'path':'memory.json'}}))
            output=root/'configured'
            result=subprocess.run([sys.executable,'-m','memfolder.loading','--config',str(config),
                '--output-dir',str(output)],env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(load_library(output/'library.json'),load_mem0(path))
            self.assertNotIn('PRIVATE_MEMORY_TEXT',result.stdout+(output/'binding.json').read_text())
            with self.assertRaises(FileExistsError):
                (output/'binding.json').open('x')

    def test_public_registry_import_does_not_load_frameworks_or_open_stores(self):
        import os
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')}
        result=subprocess.run([sys.executable,'-S','-c',
            'import sys;import memfolder.plugins;assert not any(m in sys.modules for m in ("numpy","qdrant_client","mem0","memos","mmagent"))'],
            env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
