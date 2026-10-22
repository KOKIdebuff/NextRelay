"""Bounded, inert local format conversion. No network, execution or semantics."""
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import PureWindowsPath
import re

PROCESSOR = 'nextrelay-format/1'
MAX_FILE = 5 * 1024 * 1024
MAX_BATCH = 25 * 1024 * 1024
MAX_FILES = 20
MAX_OUTPUT = 8 * 1024 * 1024
JSON_DEPTH = 32
JSON_NODES = 20_000
TOKEN_LIMIT = 1_048_576


class ImportFailure(ValueError):
    """Only fixed public codes cross the service boundary; never input excerpts."""
    def __init__(self, code, stage='parse'):
        self.code, self.stage = code, stage
        super().__init__(code)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def display_name(name):
    # Names are display only; reject Windows aliases even on non-Windows hosts.
    if (not isinstance(name, str) or not name or len(name) > 255 or
        any(ord(c) < 32 for c in name) or any(c in name for c in '/\\:<>"|?*') or
        name.endswith((' ', '.')) or PureWindowsPath(name).is_reserved() or name in ('.', '..')):
        raise ImportFailure('invalid_display_name', 'selection')
    return name


def _json_budget(text):
    # Scan *before* constructing any JSON object. Count punctuation and primitive
    # starts conservatively, bounding allocations even for malformed inputs.
    depth = nodes = token = 0
    quoted = escaped = False
    for ch in text:
        if quoted:
            token += 1
            if token > TOKEN_LIMIT:
                raise ImportFailure('json_token_limit')
            if escaped:
                escaped = False
            elif ch == '\\':
                escaped = True
            elif ch == '"':
                quoted = False
            continue
        if ch == '"':
            quoted, token = True, 0
            nodes += 1
        elif ch in '[{':
            depth += 1
            nodes += 1
            if depth > JSON_DEPTH:
                raise ImportFailure('json_depth_limit')
        elif ch in ']}':
            depth -= 1
        elif ch in ',:':
            nodes += 1
            token = 0
        elif not ch.isspace():
            token += 1
            if token == 1:
                nodes += 1
            if token > TOKEN_LIMIT:
                raise ImportFailure('json_token_limit')
        else:
            token = 0
        if nodes > JSON_NODES:
            raise ImportFailure('json_node_limit')


def formal_json(text):
    _json_budget(text)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ImportFailure('json_duplicate_key')
            result[key] = value
        return result
    def number(value):
        v = float(value)
        if not math.isfinite(v):
            raise ImportFailure('json_nonfinite')
        return v
    def constant(_):
        raise ImportFailure('json_nonfinite')
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=number, parse_constant=constant)
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        if isinstance(error, ImportFailure):
            raise
        raise ImportFailure('json_malformed') from None
    if not isinstance(value, dict) or set(value) != {'protocol','version','documents'}:
        raise ImportFailure('json_protocol_fields')
    if value['protocol'] != 'nextrelay.import' or type(value['version']) is not int or value['version'] != 1:
        raise ImportFailure('json_protocol_version')
    docs = value['documents']
    if not isinstance(docs, list) or not 1 <= len(docs) <= 100:
        raise ImportFailure('json_documents')
    ids = set()
    for doc in docs:
        if (not isinstance(doc, dict) or not {'id','title','text'} <= set(doc) or
            set(doc) - {'id','title','text','references'}):
            raise ImportFailure('json_document_fields')
        for key, limit in (('id',128), ('title',512), ('text',TOKEN_LIMIT)):
            if not isinstance(doc[key], str) or len(doc[key]) > limit or (key != 'text' and not doc[key].strip()):
                raise ImportFailure('json_document_type')
        if doc['id'] in ids:
            raise ImportFailure('json_duplicate_document')
        ids.add(doc['id'])
        refs = doc.get('references', [])
        if not isinstance(refs, list) or len(refs) > 100 or any(not isinstance(r,str) or len(r)>128 for r in refs):
            raise ImportFailure('json_references')
    if any(r not in ids for doc in docs for r in doc.get('references', [])):
        raise ImportFailure('json_reference_missing')
    return value


class StaticHTML(HTMLParser):
    BLOCK = {'p','div','br','section','article','li','tr','h1','h2','h3','h4','h5','h6'}
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    IGNORE = {'script','style','template','iframe','object','head','noscript'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts, self.headings, self.tables = [], [], []
        self.heading = self.table = self.row = self.cell = None
        self.units = self.cells = 0
        self.malformed = False

    def add(self, data):
        # Up to 4 UTF-8 bytes per code point plus JSON quoting. Charge output
        # conservatively before append and perform exact final encoding check.
        self.units += len(data.encode('utf-8'))
        if self.units > MAX_OUTPUT // 2:
            raise ImportFailure('output_limit')
        self.parts.append(data)
        if self.heading is not None:
            self.heading['parts'].append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        style = re.sub(r'\s+', '', a.get('style') or '').lower()
        hidden = (tag in self.IGNORE or 'hidden' in a or (a.get('aria-hidden') or '').lower()=='true' or
                  'display:none' in style or 'visibility:hidden' in style or bool(self.stack and self.stack[-1][1]))
        if tag not in self.VOID:
            if len(self.stack) >= 128:
                raise ImportFailure('html_depth_limit')
            self.stack.append((tag, hidden))
        if hidden:
            return
        if tag in self.BLOCK:
            self.add('\n')
        if re.fullmatch('h[1-6]',tag):
            self.heading = {'level':int(tag[1]),'line':self.getpos()[0],'parts':[]}
        if tag == 'table':
            if self.table is not None:
                raise ImportFailure('html_nested_table')
            if len(self.tables) >= 100:
                raise ImportFailure('html_table_limit')
            self.table = {'line':self.getpos()[0],'rows':[]}
            self.tables.append(self.table)
        elif tag == 'tr' and self.table is not None:
            self.row=[]
            self.table['rows'].append(self.row)
        elif tag in ('td','th') and self.row is not None:
            self.cells += 1
            if self.cells > 10_000:
                raise ImportFailure('html_cell_limit')
            self.cell=[]

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        hidden = bool(self.stack and self.stack[-1][1])
        if not self.stack or self.stack[-1][0] != tag:
            self.malformed = True
        # Tolerant extraction with explicit warning, never browser rendering.
        found = next((i for i in range(len(self.stack)-1,-1,-1) if self.stack[i][0]==tag), None)
        if found is not None:
            del self.stack[found:]
        if hidden:
            return
        if tag in ('td','th') and self.cell is not None:
            if self.row is not None:
                self.row.append(''.join(self.cell).strip())
            self.cell=None
        if tag == 'tr':
            self.row=None
        if tag == 'table':
            self.table=self.row=self.cell=None
        if re.fullmatch('h[1-6]',tag) and self.heading is not None:
            h=self.heading
            self.headings.append({'level':h['level'],'line':h['line'],'text':''.join(h['parts']).strip()})
            self.heading=None
        if tag in self.BLOCK:
            self.add('\n')

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.add(data)


TYPES = {'.txt':('text','text/plain'), '.md':('markdown','text/markdown'),
         '.markdown':('markdown','text/markdown'), '.json':('json','application/json'),
         '.html':('html','text/html'), '.htm':('html','text/html')}


def parse(data, name, media_type=None):
    if len(data) > MAX_FILE:
        raise ImportFailure('file_size_limit','read')
    selected=TYPES.get(PureWindowsPath(name).suffix.lower())
    if selected is None:
        raise ImportFailure('unsupported_format','format')
    kind,mime=selected
    if media_type is not None and media_type.lower().strip() != mime:
        raise ImportFailure('mime_mismatch','format')
    signatures=(b'%PDF-',b'PK\x03\x04',b'PK\x05\x06',b'\x89PNG',b'GIF87',b'GIF89',b'\xff\xd8\xff',b'\x1f\x8b')
    if data.startswith(signatures):
        raise ImportFailure('content_mismatch','format')
    try:
        text=data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ImportFailure('invalid_utf8','decode') from None
    if '\x00' in text:
        raise ImportFailure('binary_or_unsupported_encoding','decode')
    stripped=text.lstrip().lower()
    looks_html=bool(re.match(r'<(?:!doctype\s+html|html|head|body|h[1-6]|table|script|div|p)(?:\s|>)',stripped))
    if kind in ('text','markdown') and (looks_html or stripped.startswith(('{','['))):
        raise ImportFailure('content_mismatch','format')
    result={'processor':PROCESSOR,'format':kind,'source_sha256':digest(data),'byte_size':len(data),'warnings':[]}
    if kind in ('text','markdown'):
        result.update(text=text,locator={'kind':'line','first':1,'count':len(text.splitlines())})
    elif kind == 'json':
        result.update(protocol=formal_json(text),locator={'kind':'json-pointer','root':'/documents'})
    else:
        if stripped and not stripped.startswith('<'):
            raise ImportFailure('content_mismatch','format')
        html=StaticHTML()
        try:
            html.feed(text);html.close()
        except (RecursionError, AssertionError):
            raise ImportFailure('html_malformed') from None
        if html.malformed or html.stack:
            result['warnings'].append('tolerant_html_incomplete_or_malformed')
        result.update(text=''.join(html.parts).strip(),headings=html.headings,tables=html.tables,
                      locator={'kind':'html-source-line'})
    # Charge JSON string escaping BEFORE the encoder allocates a large string
    # token. iterencode alone can allocate 6x a control-heavy input at once.
    pending=[result];estimate=0
    while pending:
        value=pending.pop()
        if isinstance(value,dict):
            estimate+=2+2*len(value)
            pending.extend(value.keys());pending.extend(value.values())
        elif isinstance(value,list):
            estimate+=2+len(value);pending.extend(value)
        elif isinstance(value,str):
            estimate+=2
            for ch in value:
                n=ord(ch)
                estimate+=(6 if n<32 else 2 if ch in ('"','\\') else 1 if n<128 else 2 if n<2048 else 3 if n<65536 else 4)
                if estimate>MAX_OUTPUT:
                    raise ImportFailure('output_limit')
        else:
            estimate+=len(str(value))+1
        if estimate>MAX_OUTPUT:
            raise ImportFailure('output_limit')
    # iterencode then enforces the exact final byte budget as well.
    chunks=[];total=0
    encoder=json.JSONEncoder(ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    try:
        for chunk in encoder.iterencode(result):
            chunk=chunk.encode('utf-8');total+=len(chunk)
            if total>MAX_OUTPUT:
                raise ImportFailure('output_limit')
            chunks.append(chunk)
    except UnicodeEncodeError:
        raise ImportFailure('invalid_unicode') from None
    return result,b''.join(chunks)
