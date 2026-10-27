"""Code-only T10 browser harness; independent synthetic database required."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from wsgiref.simple_server import make_server
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from github_support import github_server,C2,blob
from nextrelay.config import load_settings
from nextrelay.app import create_app
from nextrelay.__main__ import QuietHandler

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--capture',required=True);ap.add_argument('--mode',required=True);args=ap.parse_args()
    capture=Path(args.capture);mode=Path(args.mode);settings=load_settings()
    if settings.model.provider!='disabled':raise ValueError('No real models in synthetic GitHub verification')
    with github_server() as remote:
        def behavior(path):
            records=json.loads(capture.read_text(encoding='utf-8')) if capture.exists() else []
            records.append({'path':path,'headers':remote.headers[-1]});capture.write_text(json.dumps(records),encoding='utf-8')
            setting=mode.read_text(encoding='utf-8') if mode.exists() else ''
            if setting=='new':remote.commit=C2
            if setting=='fail' and path.endswith('/git/blobs/'+blob(b'# Doc\nSynthetic measurement\n')):return 500,{}
        remote.behavior=behavior
        with make_server('127.0.0.1',settings.port,create_app(replace(settings,github=remote.config)),handler_class=QuietHandler) as server:
            print('T10 synthetic controlled GitHub ready',flush=True);server.serve_forever()
if __name__=='__main__':main()
