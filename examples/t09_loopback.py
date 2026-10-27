"""TEST ONLY: managed synthetic supplier injection; never enabled by production config.

Launch only against a new independent synthetic DB. The capture contains synthetic
request bodies intentionally for assertions; never use real documents/credentials.
"""
import argparse
from pathlib import Path
import json
import sys
from dataclasses import replace
from wsgiref.simple_server import make_server
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from model_support import supplier
from nextrelay.config import load_settings
from nextrelay.app import create_app
from nextrelay.__main__ import QuietHandler


def main():
    parser=argparse.ArgumentParser(description='T09 SYNTHETIC LOOPBACK TEST ONLY')
    parser.add_argument('--capture',required=True);parser.add_argument('--mode',required=True)
    args=parser.parse_args();capture=Path(args.capture);mode=Path(args.mode)
    settings=load_settings()
    if settings.model.provider!='disabled':raise ValueError('This harness requires normal model processing disabled')
    with supplier() as state:
        def behavior(payload,index):
            prior=json.loads(capture.read_text(encoding='utf-8')) if capture.exists() else []
            prior.append(dict(body=state.requests[-1]['body'].decode('utf-8'),client_request_id=state.requests[-1]['headers'].get('X-Client-Request-Id')))
            capture.write_text(json.dumps(prior),encoding='utf-8')
            if mode.exists() and mode.read_text(encoding='utf-8')=='drop':return None
            return state.respond(payload,index)
        state.behavior=behavior
        with make_server('127.0.0.1',settings.port,create_app(replace(settings,model=state.config)),handler_class=QuietHandler) as server:
            print('SYNTHETIC LOOPBACK TEST ready',flush=True);server.serve_forever()


if __name__=='__main__':main()
