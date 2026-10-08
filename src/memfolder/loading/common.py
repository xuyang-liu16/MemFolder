"""Shared validation, explicit time interpretation, and dense-vector decoding."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memfolder.core import ContractError, FrozenMap, TimePoint, TimeRange
from memfolder.core.values import require
from .types import ImportIssue, LoadOptions


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
        if not isinstance(current, dict) or key not in current:
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
    issues = []
    raw = row.get('timestamp', meta.get('timestamp'))
    timestamp = parse_time(raw, options=options)
    if raw not in (None, '') and timestamp is None:
        issues.append(issue('timestamp_unparsed', source_id, location,
                            'Original timestamp retained; no time value was invented.'))
    ranges = () if timestamp is None else (TimeRange(start=timestamp, end=timestamp),)
    available = None
    if options.visibility_field:
        raw_available = field_value(row, options.visibility_field)
        available = parse_time(raw_available, options=options)
        require(raw_available is not None and available is not None,
                f'{location}: explicit visibility field is missing or cannot be parsed')
    return ranges, available, issues


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
