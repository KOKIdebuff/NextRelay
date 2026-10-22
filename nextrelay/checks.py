"""Bounded, inert builtin-v1 checks. No expressions, regex, IO or executable schemas."""
import json
from .changes import ChangeError, canonical, exact

MAX_CONTENT = 262144
MAX_CONFIG = 16384


def bounded(value, *, depth=0, budget=None, max_bytes=MAX_CONTENT, byte_budget=None):
    if budget is None:
        budget = [4096]
    if byte_budget is None:
        byte_budget = [max_bytes]
    budget[0] -= 1
    if depth > 32 or budget[0] < 0:
        raise ChangeError('check_complexity_limit')
    if isinstance(value, dict):
        for k, v in value.items():
            bounded(k, depth=depth+1, budget=budget,max_bytes=max_bytes,byte_budget=byte_budget)
            bounded(v, depth=depth+1, budget=budget,max_bytes=max_bytes,byte_budget=byte_budget)
    elif isinstance(value, list):
        for v in value:
            bounded(v, depth=depth+1, budget=budget,max_bytes=max_bytes,byte_budget=byte_budget)
    elif isinstance(value,str):
        # Reject before UTF-8/canonical allocation; aggregate budget also bounds many strings.
        if len(value)>byte_budget[0]:
            raise ChangeError('check_config_limit' if max_bytes==MAX_CONFIG else 'check_content_limit')
        byte_budget[0] -= len(value.encode('utf-8'))
        if byte_budget[0]<0:
            raise ChangeError('check_config_limit' if max_bytes==MAX_CONFIG else 'check_content_limit')
    elif type(value) is int and value.bit_length()>max_bytes*4:
        raise ChangeError('check_complexity_limit')
    elif type(value) not in (str, int, float, bool, type(None)):
        raise ChangeError('invalid_check_value')


def config(value):
    bounded(value,max_bytes=MAX_CONFIG)
    if len(canonical(value).encode('utf-8')) > MAX_CONFIG:
        raise ChangeError('check_config_limit')
    exact(value, ('protocol','type','rules'))
    if value['protocol'] != 'builtin-v1':
        raise ChangeError('unsupported_check_protocol')
    kind, rules = value['type'], value['rules']
    if kind == 'json-object':
        exact(rules, ('required','equals'))
        if not isinstance(rules['equals'], dict):
            raise ChangeError('invalid_check_rules')
        lists = [rules['required'], list(rules['equals'])]
    elif kind in ('document-sections','content-assertions'):
        exact(rules, ('required',))
        lists = [rules['required']]
    else:
        raise ChangeError('unsupported_check_type')
    for entries in lists:
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64 or any(
                not isinstance(s, str) or not s.strip() or len(s) > 256 for s in entries):
            raise ChangeError('invalid_check_rules')
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def execute(body, configuration):
    """All failed parses/limits are execution results, never false passes."""
    try:
        config(configuration)
        if len(body.encode('utf-8')) > MAX_CONTENT:
            return 'error', 'content exceeds 262144 UTF-8 bytes'
        if not body.strip():
            return 'missing', 'artifact content is empty'
        kind, rules = configuration['type'], configuration['rules']
        if kind == 'json-object':
            parsed = json.loads(body, object_pairs_hook=_object,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
            bounded(parsed)
            if not isinstance(parsed, dict):
                return 'fail', 'JSON root must be an object'
            missing = [k for k in rules['required'] if k not in parsed]
            if missing:
                return 'missing', 'missing fields: ' + ', '.join(missing)
            unequal = [k for k, v in rules['equals'].items()
                       if k not in parsed or canonical(parsed[k]) != canonical(v)]
            return ('fail', 'fixed fields differ: ' + ', '.join(unequal)) if unequal else ('pass', 'declared JSON fields only')
        if kind == 'document-sections':
            # Markdown ATX headings only; fenced code does not define document sections.
            headings, fence = set(), None
            for line in body.splitlines():
                stripped = line.lstrip()
                if stripped.startswith(('```','~~~')):
                    marker = stripped[:3]
                    if fence is None:
                        fence = marker
                    elif fence == marker:
                        fence = None
                    continue
                if fence is not None:
                    continue
                count = len(line) - len(line.lstrip('#'))
                if 1 <= count <= 6 and line[count:count+1] == ' ':
                    headings.add(line[count:].strip().rstrip('#').strip())
            absent = [s for s in rules['required'] if s not in headings]
        else:
            absent = [s for s in rules['required'] if s not in body]
        return ('missing', 'missing declarations: ' + ', '.join(absent)) if absent else ('pass', 'declared content constraints only')
    except (ChangeError, ValueError, RecursionError, OverflowError) as error:
        return 'error', error.code if isinstance(error, ChangeError) else 'malformed or excessively complex input'
