"""Immutable wire values and strict, versioned record serialization."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, dataclass, fields
from functools import lru_cache
from hashlib import sha256
import json
import math
from types import MappingProxyType, UnionType
from typing import ClassVar, Literal, Union, get_args, get_origin, get_type_hints


class ContractError(ValueError):
    """Invalid public data, incompatible versions, or violated invariants."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def identifier(value: str, label: str = "identifier") -> None:
    require(isinstance(value, str) and bool(value.strip()), f"{label} must be nonempty")


def digest(value: str, label: str = "sha256") -> None:
    require(len(value) == 64 and all(c in '0123456789abcdef' for c in value), f"Invalid {label}")


def freeze(value):
    """Copy mutable containers; reject opaque resources and nonfinite numbers."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        require(math.isfinite(value), "JSON numbers must be finite")
        return value
    if isinstance(value, FrozenMap):
        return value
    if isinstance(value, Mapping):
        return FrozenMap(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    raise ContractError(f"Not a JSON value: {type(value).__name__}")


class FrozenMap(Mapping):
    """A recursively immutable JSON object with detached dictionary storage."""
    __slots__ = ('_values',)

    def __init__(self, values: Mapping | None = None):
        if values is None:
            values = {}
        require(isinstance(values, Mapping), "Expected a JSON object")
        require(all(type(k) is str for k in values), "JSON object keys must be strings")
        object.__setattr__(self, '_values', MappingProxyType({k: freeze(v) for k, v in values.items()}))

    def __setattr__(self, name, value):
        raise AttributeError("FrozenMap is immutable")

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __hash__(self):
        return hash(tuple(sorted(self._values.items())))

    def __repr__(self):
        return f"FrozenMap({dict(self._values)!r})"


_RECORDS: dict[str, type] = {}


@lru_cache(maxsize=None)
def hints(cls):
    return get_type_hints(cls)


def normalize(annotation, value, path: str):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        for option in args:
            try:
                return normalize(option, value, path)
            except ContractError:
                pass
        raise ContractError(f"{path}: value does not match {annotation}")
    if origin is Literal:
        require(any(type(value) is type(x) and value == x for x in args), f"{path}: invalid literal")
        return value
    if origin is tuple:
        require(isinstance(value, (list, tuple)), f"{path}: expected array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(normalize(args[0], v, f"{path}[{i}]") for i, v in enumerate(value))
        require(len(value) == len(args), f"{path}: wrong tuple length")
        return tuple(normalize(t, v, path) for t, v in zip(args, value))
    if annotation is FrozenMap:
        require(isinstance(value, Mapping), f"{path}: expected JSON object")
        return FrozenMap(value)
    if annotation is float:
        require(type(value) in (int, float), f"{path}: expected number")
        try:
            converted = float(value)
        except OverflowError as exc:
            raise ContractError(f"{path}: number exceeds float range") from exc
        require(math.isfinite(converted), f"{path}: expected finite number")
        return converted
    if annotation in (str, int, bool, type(None)):
        require(type(value) is annotation, f"{path}: expected {annotation.__name__}")
        return value
    if isinstance(annotation, type) and issubclass(annotation, Contract):
        require(type(value) is annotation, f"{path}: expected {annotation.__name__}")
        return value
    raise ContractError(f"{path}: unsupported contract annotation {annotation}")


class Contract:
    """Named schemas, explicit major versions, namespaced JSON extensions."""
    schema_id: ClassVar[str]
    schema_version: ClassVar[int] = 1

    def __post_init__(self):
        for f in fields(self):
            object.__setattr__(self, f.name, normalize(hints(type(self))[f.name], getattr(self, f.name), f.name))
        if hasattr(self, 'extensions'):
            require(all('.' in k and not k.startswith('.') and not k.endswith('.')
                        for k in self.extensions), "Extension keys need a namespace, e.g. lab.routing")


def record(schema_id: str):
    """Declare a wire record. Third-party records opt in through this same API."""
    def decorate(cls):
        require(schema_id not in _RECORDS, f"Duplicate schema: {schema_id}")
        identifier(schema_id, "schema_id")
        require('.' in schema_id and '/' not in schema_id and '~' not in schema_id, 'Schema ID needs a JSON-pointer-safe namespace')
        require(issubclass(cls, Contract), 'Wire records must inherit Contract')
        cls.schema_id = schema_id
        # No slots: inherited post-init super() remains straightforward for contributors.
        cls = dataclass(frozen=True, kw_only=True)(cls)
        _RECORDS[schema_id] = cls
        return cls
    return decorate


def to_data(value):
    """Public wire representation; excludes class variables and live resources."""
    if isinstance(value, Contract):
        return {f.name: to_data(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: to_data(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_data(v) for v in value]
    return freeze(value)


def _decode(annotation, value, path):
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (UnionType, Union):
        for option in args:
            try:
                return _decode(option, value, path)
            except ContractError:
                pass
        raise ContractError(f"{path}: no matching wire type")
    if origin is tuple:
        require(type(value) is list, f"{path}: expected JSON array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode(args[0], v, path) for v in value)
        require(len(args) == len(value), f"{path}: wrong array length")
        return tuple(_decode(t, v, path) for t, v in zip(args, value))
    if isinstance(annotation, type) and issubclass(annotation, Contract):
        return from_data(annotation, value)
    return normalize(annotation, value, path)


def from_data(cls: type[Contract], value: dict):
    require(isinstance(cls, type) and issubclass(cls, Contract), "Expected a contract class")
    require(type(value) is dict, f"{cls.__name__}: expected JSON object")
    fs = {f.name: f for f in fields(cls)}
    require(not set(value) - set(fs), f"Unknown fields in {cls.__name__}: {set(value) - set(fs)}")
    required = {n for n, f in fs.items() if f.default is MISSING and f.default_factory is MISSING}
    require(required <= set(value), f"Missing fields in {cls.__name__}: {required - set(value)}")
    return cls(**{k: _decode(hints(cls)[k], v, k) for k, v in value.items()})


def fingerprint(value) -> str:
    return sha256(json.dumps(to_data(value), ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def dumps(value: Contract, *, indent: int | None = None) -> str:
    require(isinstance(value, Contract), "Only declared contracts have wire envelopes")
    return json.dumps({'schema_id': value.schema_id, 'schema_version': value.schema_version,
                       'data': to_data(value)}, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, indent=indent)


def loads(text: str, *, expected: type[Contract] | None = None) -> Contract:
    def pairs(items):
        require(len(items) == len({k for k, _ in items}), "Duplicate JSON key")
        return dict(items)
    try:
        wire = json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(ContractError(f"Invalid number {x}")))
    except (ValueError, TypeError) as exc:
        raise ContractError(f"Invalid JSON: {exc}") from exc
    require(type(wire) is dict and set(wire) == {'schema_id', 'schema_version', 'data'}, "Invalid wire envelope")
    require(type(wire['schema_id']) is str and wire['schema_id'] in _RECORDS, "Unknown schema; register it explicitly")
    cls = _RECORDS[wire['schema_id']]
    require(type(wire['schema_version']) is int and wire['schema_version'] == cls.schema_version, "Unsupported schema version")
    require(expected is None or cls is expected, "Unexpected wire schema")
    return from_data(cls, wire['data'])


def json_schema(cls: type[Contract]) -> dict:
    """Generate structural schemas; semantic checks still run in constructors."""
    definitions = {}

    def typed(t):
        origin, args = get_origin(t), get_args(t)
        if origin in (UnionType, Union):
            return {'anyOf': [typed(a) for a in args]}
        if origin is Literal:
            return {'enum': list(args)}
        if origin is tuple:
            if len(args) == 2 and args[1] is Ellipsis:
                return {'type': 'array', 'items': typed(args[0])}
            return {'type': 'array', 'prefixItems': [typed(a) for a in args],
                    'minItems': len(args), 'maxItems': len(args)}
        if t is FrozenMap:
            return {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/JSONValue'}}
        if t in (str, int, float, bool, type(None)):
            return {'type': {str: 'string', int: 'integer', float: 'number', bool: 'boolean', type(None): 'null'}[t]}
        if isinstance(t, type) and issubclass(t, Contract):
            if t.schema_id not in definitions:
                definitions[t.schema_id] = {}
                fs = fields(t)
                definitions[t.schema_id] = {'type': 'object', 'additionalProperties': False,
                    'properties': {f.name: typed(hints(t)[f.name]) for f in fs},
                    'required': [f.name for f in fs if f.default is MISSING and f.default_factory is MISSING]}
            return {'$ref': '#/$defs/' + t.schema_id}
        raise ContractError(f"Cannot generate schema for {t}")

    data = typed(cls)
    definitions['JSONValue'] = {'anyOf': [{'type': ['string', 'number', 'boolean', 'null']},
        {'type': 'array', 'items': {'$ref': '#/$defs/JSONValue'}},
        {'type': 'object', 'additionalProperties': {'$ref': '#/$defs/JSONValue'}}]}
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$comment': 'Structural schema. Semantic invariants are enforced by memfolder.core.',
            'type': 'object', 'additionalProperties': False,
            'required': ['schema_id', 'schema_version', 'data'],
            'properties': {'schema_id': {'const': cls.schema_id}, 'schema_version': {'const': cls.schema_version}, 'data': data},
            '$defs': definitions}
