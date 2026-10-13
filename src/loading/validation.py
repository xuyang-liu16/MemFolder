"""Shared validation, explicit time interpretation, and dense-vector decoding."""

from __future__ import annotations
from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .contracts import ImportIssue, LoadOptions
from ..core import ContractError, FrozenMap, TimePoint, TimeRange
from ..core.values import require


def object_value(value, location: str) -> dict:
    require(type(value) is dict, f'{location}: expected JSON object')
    return value


def array_value(value, location: str) -> list:
    require(type(value) is list, f'{location}: expected JSON array')
    return value


def native_id(value, location: str) -> str:
    require(type(value) in (str, int) and bool(str(value).strip()), f'{location}: missing/invalid native ID')
    return str(value)


def text_value(value, location: str) -> str:
    require(type(value) is str, f'{location}: expected text')
    return value  # whitespace is part of the original content


def metadata(row: dict, location: str) -> dict:
    value = row.get('metadata')
    return {} if value is None else object_value(value, location + '.metadata')


def issue(code: str, source_id: str, location: str, message: str, *, severity='warning') -> ImportIssue:
    return ImportIssue(code=code, source_id=source_id, location=location, message=message, severity=severity)


def strict_json(text: str, location: str):
    def pairs(items):
        require(len(items) == len({k for k, _ in items}), f'{location}: duplicate JSON key')
        return dict(items)
    def constant(_):
        raise ContractError(f'{location}: nonfinite JSON number')
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        FrozenMap({'value': value})  # validate all numbers, including overflow to infinity
        return value
    except (ValueError, TypeError, RecursionError) as ex:
        raise ContractError(f'{location}: invalid JSON ({type(ex).__name__})') from None


def dense_vectors(value, location: str) -> tuple[tuple[float, ...], ...]:
    """Accept a dense vector or multiple dense vectors; never silently pick one."""
    if value is None or value == []:
        return ()
    values = array_value(value, location)
    if values and type(values[0]) in (int, float):
        values = [values]
    result = []
    for row in values:
        row = array_value(row, location)
        require(bool(row), f'{location}: empty vector')
        converted = []
        for n in row:
            require(type(n) in (int, float), f'{location}: expected numeric dense vector')
            try:
                n = float(n)
            except OverflowError:
                raise ContractError(f'{location}: vector value overflows') from None
            require(math.isfinite(n), f'{location}: nonfinite vector value')
            converted.append(n)
        result.append(tuple(converted))
    require(len({len(v) for v in result}) <= 1, f'{location}: inconsistent vector dimensions')
    return tuple(result)


def field_value(row: dict, name: str):
    current = row
    for key in name.split('.'):
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def parse_time(value, *, options: LoadOptions) -> TimePoint | None:
    """No epoch-zero fallback and no inferred numeric clock/unit."""
    if value is None or value == '':
        return None
    if type(value) in (int, float) and options.numeric_timestamp_clock is not None:
        return TimePoint(value=value, clock=options.numeric_timestamp_clock)
    if type(value) is not str:
        return None
    clean = re.sub(r'\b(am|pm)\b', lambda m: m.group(1).upper(), value.strip(), flags=re.I)
    try:
        parsed = datetime.fromisoformat(clean.replace('Z', '+00:00'))
    except ValueError:
        parsed = None
        for pattern in ('%I:%M %p on %d %B, %Y', '%I:%M %p on %d %b, %Y'):
            try:
                parsed = datetime.strptime(clean, pattern)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        if options.naive_timezone is None:
            return None
        try:
            tz = timezone.utc if options.naive_timezone == 'UTC' else ZoneInfo(options.naive_timezone)
        except ZoneInfoNotFoundError:
            raise ContractError('Configured naive timestamp timezone is unavailable') from None
        parsed = parsed.replace(tzinfo=tz)
        # Reject ambiguous/nonexistent wall-clock values instead of guessing a fold.
        if parsed.utcoffset() != parsed.replace(fold=1).utcoffset():
            return None
        if parsed.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) != parsed.replace(tzinfo=None):
            return None
    return TimePoint(value=parsed.timestamp(), clock='unix_seconds')


def temporal_fields(row: dict, meta: dict, options: LoadOptions, source_id: str, location: str):
    """Compatibility view of the explicit temporal projection."""
    return temporal_projection(row, meta, options, source_id, location)[:3]


def _lineage_time_point(value, location: str) -> TimePoint | None:
    if value is None:
        return None
    value = object_value(value, location)
    require(set(value) == {'value', 'clock'}, f'{location}: invalid time point')
    return TimePoint(value=value['value'], clock=value['clock'])


def _lineage_time_range(value, location: str) -> TimeRange:
    value = object_value(value, location)
    require(set(value) == {'start', 'end'}, f'{location}: invalid time range')
    return TimeRange(start=_lineage_time_point(value['start'], location + '.start'),
                     end=_lineage_time_point(value['end'], location + '.end'))


def lineage_temporal_projection(row: dict, meta: dict, location: str):
    """Restore exact canonical time fields written by a MemFolder native codec.

    Native timestamps remain a framework-facing projection.  The namespaced
    lineage preserves the full event ranges and visibility interval so a
    MemFolder export can be loaded again without widening visibility.
    """
    top, nested = row.get('memfolder'), meta.get('memfolder')
    require(top is None or nested is None or top == nested,
            f'{location}: conflicting MemFolder lineage')
    value = top if top is not None else nested
    if value is None:
        return None
    value = object_value(value, location + '.memfolder')
    schema = value.get('schema')
    require(schema in (None, 'memfolder.lineage.v1'),
            f'{location}: unsupported MemFolder lineage schema')
    temporal = {'time_ranges', 'available_at', 'expires_at'}
    if not temporal.intersection(value):
        return None
    require(temporal <= set(value), f'{location}: incomplete MemFolder temporal lineage')
    raw_ranges = value['time_ranges']
    require(type(raw_ranges) is list, f'{location}.memfolder.time_ranges: expected array')
    ranges = tuple(_lineage_time_range(item, f'{location}.memfolder.time_ranges[{index}]')
                   for index, item in enumerate(raw_ranges))
    available = _lineage_time_point(value['available_at'], location + '.memfolder.available_at')
    expires = _lineage_time_point(value['expires_at'], location + '.memfolder.expires_at')
    require(available is None or expires is None or
            available.clock == expires.clock and available.value <= expires.value,
            f'{location}: invalid MemFolder visibility interval')
    return ranges, available, expires


def temporal_projection(row: dict, meta: dict, options: LoadOptions, source_id: str, location: str):
    issues = []
    timestamp = None
    selected = None
    present = False
    for name in options.timestamp_fields:
        raw = field_value(row, name) if name.split('.')[0] in row else field_value(meta, name)
        present |= raw not in (None, '')
        timestamp = parse_time(raw, options=options)
        if timestamp is not None:
            selected = name
            break
    if present and timestamp is None:
        issues.append(issue('timestamp_unparsed', source_id, location,
                            'Original timestamp retained; no time value was invented.'))
    ranges = () if timestamp is None else (TimeRange(start=timestamp, end=timestamp),)
    available = None
    if options.visibility_field:
        raw_available = field_value(row, options.visibility_field)
        available = parse_time(raw_available, options=options)
        require(raw_available is not None and available is not None,
                f'{location}: explicit visibility field is missing or cannot be parsed')
    extensions = {}
    if options.timestamp_fields != ('timestamp',) or options.time_semantics != 'event_time':
        extensions['memfolder.temporal_source'] = {
            'fields': options.timestamp_fields, 'selected_field': selected,
            'semantics': options.time_semantics,
            'clock': timestamp.clock if timestamp is not None else None}
    return ranges, available, issues, extensions


def check_coverage(data: dict, nodes: int, edges: int, source_id: str):
    partial = False
    for key, count in (('total_nodes', nodes), ('total_edges', edges)):
        if key in data:
            require(type(data[key]) is int and data[key] >= count, f'{source_id}: invalid declared total')
            partial |= data[key] != count
    partial |= data.get('next_page_offset') is not None or data.get('next') is not None
    if partial:
        return 'partial'
    return 'declared_complete' if 'total_nodes' in data and 'total_edges' in data else 'unknown'
