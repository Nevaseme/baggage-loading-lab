"""Build a reproducible submission ZIP for a self-contained pure-Python Agent."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import keyword
from pathlib import Path
import re
import zipfile


def build_package(source: Path, package_name: str, output: Path) -> dict:
    source=Path(source).resolve()
    output=Path(output)
    if not re.fullmatch(r'[a-z][a-z0-9_]*',package_name) or keyword.iskeyword(package_name):
        raise ValueError('package_name must be an importable snake_case name')
    if output.exists():
        raise FileExistsError(output)
    if not (source/'agent.py').is_file():
        raise ValueError('source must contain agent.py')
    payloads={}
    for path in sorted(source.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        if not path.resolve().is_relative_to(source):
            raise ValueError('source files must stay inside the package')
        payload=path.read_bytes()
        ast.parse(payload,filename=str(path))
        payloads[path.relative_to(source).as_posix()]=payload
    payloads.setdefault('__init__.py',b'')
    manifest={'schema_version':1,'package_name':package_name,
              'source_sha256':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(payloads.items())}}
    payloads['PACKAGE.json']=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,data in sorted(payloads.items()):
            entry=zipfile.ZipInfo(package_name+'/'+name,date_time=(1980,1,1,0,0,0))
            entry.create_system=3
            entry.external_attr=0o100644<<16
            entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    return {'output':str(output.resolve()),'package_name':package_name,
            'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'source_sha256':manifest['source_sha256'],'file_count':len(payloads)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--package-name',required=True)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(build_package(args.source,args.package_name,args.output),sort_keys=True))


if __name__=='__main__': main()
