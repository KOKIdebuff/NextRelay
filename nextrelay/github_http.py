"""T10 credential-free GitHub GET transport. Only server-built API paths.

No environment proxies, redirects, credentials, download_url, or raw host access.
The test endpoint is an explicit in-process injection, unavailable in env config.
"""
from dataclasses import dataclass, field
import http.client
import ipaddress
import json
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit, unquote, quote
from .formats import ImportFailure, _json_budget

TIMEOUT=20
MAX_FILES=100
MAX_CONTENT=10*1024*1024
MAX_ENTRIES=2000
MAX_METADATA=2*1024*1024
MAX_REQUESTS=128
OP_SECONDS=120
_DNS=threading.BoundedSemaphore(4)
SHA=re.compile(r'[0-9a-f]{40}')


def fail(code):
    raise ImportFailure('github_'+code,'remote')


def path_value(value, *, empty=False):
    if not isinstance(value,str) or len(value)>1024 or (not value and not empty):fail('invalid_path')
    try:value.encode('utf-8')
    except UnicodeError:fail('invalid_path')
    if value and (any(c in value for c in '\\%?#:') or any(ord(c)<32 or ord(c)==127 for c in value) or
                  any(p in ('','.','..') for p in value.split('/'))):fail('invalid_path')
    return value


def parse_url(value):
    if not isinstance(value,str) or not 1<=len(value)<=2048 or any(ord(c)<=32 or ord(c)==127 for c in value):fail('invalid_url')
    try:
        u=urlsplit(value)
        if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:fail('invalid_url')
        port=u.port
    except ValueError:fail('invalid_url')
    if u.hostname.lower()!='github.com':
        return dict(kind='reference',url=value)
    if u.scheme!='https' or port is not None or u.netloc.lower()!='github.com' or u.query or u.fragment:fail('invalid_url')
    if re.search(r'%(?![0-9a-fA-F]{2})',u.path):fail('invalid_url')
    try:p=unquote(u.path,errors='strict').strip('/')
    except UnicodeError:fail('invalid_url')
    path_value(p)
    parts=p.split('/')
    if len(parts)<2 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',parts[0]) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',parts[1]) or parts[1] in ('.','..'):fail('invalid_repository')
    repo=parts[1].removesuffix('.git')
    if not repo:fail('invalid_repository')
    if len(parts)==2:kind='repository';tail=''
    elif len(parts)>=4 and parts[2] in ('tree','blob'):kind=parts[2];tail='/'.join(parts[3:])
    else:fail('unsupported_github_link')
    return dict(kind=kind,url=value,owner=parts[0],repo=repo,tail=tail)


def public_unicast(value):
    ip=ipaddress.ip_address(value)
    mapped=getattr(ip,'ipv4_mapped',None)
    return (ip.is_global and not any((ip.is_multicast,ip.is_reserved,ip.is_unspecified,
        ip.is_loopback,ip.is_link_local,getattr(ip,'is_site_local',False))) and
        (mapped is None or public_unicast(str(mapped))))


def addresses(deadline):
    if not _DNS.acquire(timeout=max(0,deadline-time.monotonic())):fail('dns_busy')
    result=queue.Queue(1)
    def resolve():
        try:
            a=socket.getaddrinfo('api.github.com',443,type=socket.SOCK_STREAM)
            result.put(a if len(a)<=64 else None)
        except OSError:result.put(None)
        finally:_DNS.release()
    threading.Thread(target=resolve,daemon=True,name='nextrelay-github-dns').start()
    try:a=result.get(timeout=max(0,deadline-time.monotonic()))
    except queue.Empty:fail('dns_timeout')
    if not a or any(not public_unicast(x[4][0]) for x in a):fail('target_denied')
    return a


def json_value(raw):
    try:
        text=raw.decode('utf-8');_json_budget(text)
        def pairs(items):
            result={}
            for k,v in items:
                if k in result:raise ValueError()
                result[k]=v
            return result
        value=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:fail('invalid_response'))
        # Reject lone surrogates before any manifest/database serialization.
        json.dumps(value,ensure_ascii=False).encode('utf-8')
        return value
    except (ValueError,UnicodeError,RecursionError):fail('invalid_response')


@dataclass(frozen=True)
class GitHubConfig:
    _test_endpoint: str | None = field(default=None,repr=False)
    timeout: float = TIMEOUT

    def __post_init__(self):
        if not 0<self.timeout<=TIMEOUT:raise ValueError('GitHub timeout must be <=20s')
        if self._test_endpoint is not None:
            u=urlsplit(self._test_endpoint)
            if u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.path or u.query or u.fragment or u.username:raise ValueError('Explicit loopback injection only')


class GitHubHTTP:
    def __init__(self,config=None):self.config=config or GitHubConfig();self.requests=[]

    def get(self,path,limit,*,deadline=None,charge=None,raw=False,sha_only=False):
        # Constructed from validated segments; never a server-supplied URL.
        if not re.fullmatch(r'/repos/[A-Za-z0-9_.%-]+/[A-Za-z0-9_.%-]+(?:/[A-Za-z0-9_./%?=&-]+)?',path) or any(x in ('.','..') for x in unquote(path).split('/')) or '%25' in path.lower():fail('target_denied')
        end=min(deadline or float('inf'),time.monotonic()+self.config.timeout)
        c=timer=None
        try:
            if self.config._test_endpoint:
                u=urlsplit(self.config._test_endpoint);c=http.client.HTTPConnection('127.0.0.1',u.port,timeout=max(.001,end-time.monotonic()))
            else:
                a=addresses(end);ip=a[0][4][0]
                c=http.client.HTTPSConnection('api.github.com',443,timeout=max(.001,end-time.monotonic()))
                def pinned():
                    sock=socket.create_connection((ip,443),timeout=max(.001,end-time.monotonic()))
                    try:
                        sock.settimeout(max(.001,end-time.monotonic()))
                        c.sock=ssl.create_default_context().wrap_socket(sock,server_hostname='api.github.com')
                    except BaseException:sock.close();raise
                c.connect=pinned
            if time.monotonic()>=end:fail('timeout')
            c.connect();sock=c.sock
            def expire():
                try:sock.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            timer=threading.Timer(max(0,end-time.monotonic()),expire);timer.daemon=True;timer.start()
            self.requests.append(path)
            c.request('GET',path,headers={'Accept':'application/vnd.github.sha' if sha_only else 'application/vnd.github.raw+json' if raw else 'application/vnd.github+json',
                'X-GitHub-Api-Version':'2022-11-28','User-Agent':'NextRelay/0.10','Accept-Encoding':'identity'})
            res=c.getresponse()
            if 300<=res.status<400:fail('redirect_denied')
            if res.status in (403,429):fail('rate_limited_manual_retry')
            if res.status!=200:fail('http_'+str(res.status))
            if res.getheader('Content-Encoding','identity')!='identity':fail('encoding_denied')
            if not raw and not sha_only and res.getheader('Content-Type','').split(';')[0]!='application/json':fail('json_required')
            data=bytearray()
            while True:
                if time.monotonic()>=end:fail('timeout')
                block=res.read1(min(8192,limit+1-len(data)))
                if not block:break
                if charge:charge(len(block))
                data.extend(block)
                if len(data)>limit:fail('stream_limit')
            if sha_only:
                if not re.fullmatch(rb'[0-9a-f]{40}\n?',bytes(data)):fail('commit_unpinned')
                return bytes(data).strip().decode('ascii')
            return bytes(data) if raw else json_value(bytes(data))
        except (OSError,http.client.HTTPException):fail('transport_or_timeout')
        finally:
            if timer:timer.cancel();timer.join()
            if c:c.close()


def segment(value):return quote(value,safe='')
