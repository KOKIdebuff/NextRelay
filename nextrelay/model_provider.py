"""Official Responses wire adapter. No SDK retries, proxies, redirects or tools.

References: https://developers.openai.com/api/docs/guides/structured-outputs
https://developers.openai.com/api/reference/overview#debugging-requests
X-Client-Request-Id is diagnostic identity, NOT an exactly-once guarantee.
"""
from dataclasses import dataclass, field
import http.client
import ipaddress
import re
import socket
import ssl
import time
import threading
import queue
from urllib.parse import urlsplit
from .changes import ChangeError, canonical
from .model_protocol import MAX_RESPONSE, strict_json, bounded_text

ENDPOINT = 'https://api.openai.com/v1/responses'
_DNS_SLOTS=threading.BoundedSemaphore(4)


def public_addresses(deadline):
    # Host resolver calls have no portable per-call timeout. A bounded daemon
    # pool holds no payload/credential and limits both wait time and stuck work.
    remaining=max(0,deadline-time.monotonic())
    if not _DNS_SLOTS.acquire(timeout=remaining):raise ProviderFailure('model_dns_busy')
    result=queue.Queue(maxsize=1)
    def resolve():
        try:
            addresses=socket.getaddrinfo('api.openai.com',443,type=socket.SOCK_STREAM)
            result.put(addresses if len(addresses)<=64 else None)
        except OSError:result.put(None)
        finally:_DNS_SLOTS.release()
    threading.Thread(target=resolve,daemon=True,name='nextrelay-model-dns').start()
    try:addresses=result.get(timeout=max(0,deadline-time.monotonic()))
    except queue.Empty:raise ProviderFailure('model_dns_timeout') from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ProviderFailure('model_target_denied')
    return addresses



@dataclass(frozen=True)
class ModelConfig:
    provider: str = 'disabled'
    model: str = ''
    api_key: str = field(default='',repr=False,compare=False)
    endpoint: str = ENDPOINT
    timeout: float = 20
    _loopback_test: bool = field(default=False,repr=False)

    def __post_init__(self):
        if self.provider=='disabled':return
        if self.provider not in ('openai-responses','test-loopback'):raise ValueError('Unsupported model provider')
        if not re.fullmatch(r'[A-Za-z0-9._:-]{1,100}',self.model):raise ValueError('Explicit model required')
        if not 0 < self.timeout <= 20:raise ValueError('Model timeout out of range')
        if self.provider=='test-loopback':
            u=urlsplit(self.endpoint)
            if not self._loopback_test or u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.path!='/v1/responses' or u.query or u.fragment or u.username or self.api_key:
                raise ValueError('Only explicitly injected credential-free loopback tests allowed')
        elif self.endpoint!=ENDPOINT or not re.fullmatch(r'[!-~]{1,512}',self.api_key):
            raise ValueError('Official endpoint and explicit server credential required')

    def public(self):
        return dict(provider=self.provider,model=self.model,endpoint=self.endpoint,timeout=self.timeout,
                    calls_per_item=1,retries=0,max_output_tokens=4096,store=False,
                    retention='third-party retention unverified' if self.provider!='test-loopback' else 'local synthetic test only')


class ProviderFailure(Exception):
    def __init__(self,code,unknown=False):self.code,self.unknown=code,unknown


class ResponsesAdapter:
    def __init__(self,config):self.config=config

    def send(self,payload,request_id):
        cfg=self.config;u=urlsplit(cfg.endpoint);deadline=time.monotonic()+cfg.timeout
        connection=None;watchdog=None
        try:
            if cfg.provider=='test-loopback':
                connection=http.client.HTTPConnection('127.0.0.1',u.port,timeout=cfg.timeout)
            elif cfg.provider=='openai-responses' and cfg.endpoint==ENDPOINT:
                addresses=public_addresses(deadline)
                # Connect to an inspected address; TLS still verifies the official hostname.
                address=addresses[0][4][0]
                connection=http.client.HTTPSConnection('api.openai.com',443,timeout=max(.01,deadline-time.monotonic()))
                def pinned_connect():
                    sock=socket.create_connection((address,443),timeout=max(.01,deadline-time.monotonic()))
                    sock.settimeout(max(.01,deadline-time.monotonic()))
                    try:connection.sock=ssl.create_default_context().wrap_socket(sock,server_hostname='api.openai.com')
                    except BaseException:sock.close();raise
                connection.connect=pinned_connect
            else:raise ProviderFailure('model_not_configured')
            if time.monotonic()>=deadline:raise ProviderFailure('model_preflight_timeout')
            headers={'Content-Type':'application/json','Accept':'application/json','X-Client-Request-Id':request_id}
            if cfg.provider=='openai-responses':headers['Authorization']='Bearer '+cfg.api_key
            connection.connect()
            transport_socket=connection.sock
            def expire():
                try:transport_socket.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            watchdog=threading.Timer(max(0,deadline-time.monotonic()),expire)
            watchdog.daemon=True;watchdog.start()
            connection.request('POST',u.path,body=payload,headers=headers)
            response=connection.getresponse()
            # No redirect is followed, including to the same host. Do not retain error bodies.
            if 300<=response.status<500:raise ProviderFailure('model_http_'+str(response.status))
            if response.status!=200:raise ProviderFailure('model_provider_error',unknown=True)
            if response.getheader('Content-Encoding','identity')!='identity':raise ChangeError('model_encoding_denied')
            if response.getheader('Content-Type','').split(';')[0]!='application/json':raise ChangeError('model_json_required')
            data=bytearray()
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError()
                if connection.sock:connection.sock.settimeout(remaining)
                block=response.read1(min(8192,MAX_RESPONSE+1-len(data)))
                if not block:break
                data.extend(block)
                if len(data)>MAX_RESPONSE:raise ChangeError('model_response_size_limit')
            envelope=strict_json(bytes(data),token_limit=192*1024)
            if not isinstance(envelope,dict) or envelope.get('status')!='completed' or envelope.get('model')!=cfg.model:
                raise ChangeError('model_incomplete_or_wrong_model')
            output=envelope.get('output')
            if not isinstance(output,list) or not output:raise ChangeError('model_output_required')
            texts=[]
            for entry in output:
                if not isinstance(entry,dict):raise ChangeError('model_output_invalid')
                # Reasoning is inert provider output; it is never executed or persisted.
                if entry.get('type')=='reasoning':continue
                if entry.get('type')!='message' or entry.get('role')!='assistant':raise ChangeError('model_tools_denied')
                parts=entry.get('content')
                if not isinstance(parts,list):raise ChangeError('model_output_invalid')
                for part in parts:
                    if not isinstance(part,dict) or part.get('type')!='output_text':raise ChangeError('model_refusal_or_tools_denied')
                    texts.append(bounded_text(part.get('text'),128*1024))
            if len(texts)!=1:raise ChangeError('model_output_invalid')
            usage=envelope.get('usage') or {}
            if not isinstance(usage,dict):raise ChangeError('model_invalid_usage')
            safe_usage={}
            for k in ('input_tokens','output_tokens','total_tokens'):
                if k in usage:
                    if type(usage[k]) is not int or not 0<=usage[k]<=10000000:raise ChangeError('model_invalid_usage')
                    safe_usage[k]=usage[k]
            # Provider identifiers are metadata, not arbitrary text/log channels.
            identity=envelope.get('id')
            if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',identity):raise ChangeError('model_invalid_response_id')
            return texts[0].encode('utf-8'),identity,safe_usage
        except (OSError,http.client.HTTPException):
            raise ProviderFailure('model_transport_unknown',unknown=True) from None
        finally:
            if watchdog:watchdog.cancel();watchdog.join()
            if connection:connection.close()
