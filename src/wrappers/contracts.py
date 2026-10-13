"""Detached wrapper boundaries. Native clients and paths stay outside wire data."""

from __future__ import annotations
from dataclasses import dataclass
from functools import cached_property
from typing import Awaitable, Protocol
from ..core import AlgorithmContext, Contract, FrozenMap, PluginSpec, Snapshot, record
from ..core.values import digest, identifier, require


@record('memfolder.wrapper.native_package')
class NativePackage(Contract):
    framework_id: str
    format_id: str
    snapshot_fingerprint: str
    node_id_map: FrozenMap
    data: FrozenMap
    lineage: FrozenMap

    def __post_init__(self):
        super().__post_init__()
        identifier(self.framework_id); identifier(self.format_id)
        digest(self.snapshot_fingerprint)
        require(set(self.lineage) == set(self.node_id_map), 'Lineage must cover native IDs')
        require(all(type(v) is str and v for v in self.node_id_map.values()), 'Native IDs must be nonempty strings')
        require(len(set(self.node_id_map.values())) == len(self.node_id_map), 'Native IDs must be unique')


@dataclass(frozen=True)
class NativeArchive:
    snapshot: Snapshot

    @cached_property
    def records(self):
        from types import MappingProxyType
        return MappingProxyType({n.node_id: n for n in self.snapshot.records})

    @cached_property
    def origins(self):
        values = {}
        for n in self.snapshot.records:
            for origin in n.origins:
                require(origin not in values, 'Ambiguous native origin identity')
                values[origin] = n
        from types import MappingProxyType
        return MappingProxyType(values)

    def contributors(self, node):
        require(all(o in self.origins for o in node.origins), 'Output escaped the native source archive')
        return tuple({self.origins[o].node_id: self.origins[o] for o in node.origins}.values())

    def anchor(self, node):
        return next((n for n in self.contributors(node) if n.node_id == node.node_id), self.contributors(node)[0])


class NativeCodec(Protocol):
    spec: PluginSpec
    framework_id: str
    def encode(self, snapshot: Snapshot, archive: NativeArchive, context: AlgorithmContext) -> NativePackage | Awaitable[NativePackage]: ...


class NativeWriter(Protocol):
    spec: PluginSpec
    def write(self, package: NativePackage, directory, context: AlgorithmContext) -> tuple[str, ...] | Awaitable[tuple[str, ...]]: ...


class AssetCopier(Protocol):
    spec: PluginSpec
    def copy(self, snapshot: Snapshot, directory, context: AlgorithmContext) -> tuple[str, ...] | Awaitable[tuple[str, ...]]: ...
