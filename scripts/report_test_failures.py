"""Bounded, credential-filtered annotations for secret-free source CI tests.

Diagnostic only: never changes the pytest exit code or test verdict. Source CI
must not receive application/provider secrets. Artifacts/log access can require
additional authorization even when public check annotations are readable.
"""
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def safe(value):
    text = str(value)
    for name, secret in os.environ.items():
        if len(secret) >= 8 and any(x in name.upper() for x in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY')):
            text = text.replace(secret, '[redacted]')
    text = re.sub(r'(?i)\b(?:gh[pousr]_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]+|Bearer\s+[^\s\"\']+)', '[redacted]', text)
    return text[:3000].replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def annotations(path):
    p = Path(path)
    if not p.is_file() or p.stat().st_size > 5_000_000:
        return ['::error::Test failure report missing or exceeds diagnostic bound']
    try:
        root = ET.fromstring(p.read_bytes())
    except (ET.ParseError, ValueError):
        return ['::error::Test failure report could not be parsed']
    out = []
    for case in root.iter('testcase'):
        for result in case:
            if result.tag not in ('failure', 'error'):
                continue
            name = case.get('classname', '') + '.' + case.get('name', '').split('[')[0]
            name = re.sub(r'[^A-Za-z0-9_.-]', '_', name)[:180]
            out.append('::error title=Source test ' + name + '::' + safe(result.text or result.get('message', 'Test failed')))
            if len(out) >= 20:
                return out
    return out


if __name__ == '__main__':
    for annotation in annotations(sys.argv[1]):
        print(annotation)
