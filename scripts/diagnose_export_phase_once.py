"""One bounded forwarding observation; original fixture/assertions are unchanged."""
import faulthandler
import json
import os
import threading
import time
import unittest
from unittest.mock import patch
from app import gateway_transport as gt
from app import otlp_export as ot
from tests.test_otlp_cleanup_ownership import CleanupOwnershipTests

rows = []
origin = time.monotonic()
def emit(kind, **values):
    rows.append(dict(kind=kind, ms=round((time.monotonic()-origin)*1000, 3), **values))
def watchdog():
    if not done.wait(20):
        print('EXPORT_PHASE ' + json.dumps(rows), flush=True)
        faulthandler.dump_traceback()
        os._exit(124)
def forward(owner, name):
    original = getattr(owner, name)
    def observed(self, *args, **kwargs):
        begin = time.monotonic(); emit(name+'_begin')
        try:
            return original(self, *args, **kwargs)
        finally:
            emit(name+'_end', elapsed_ms=round((time.monotonic()-begin)*1000, 3))
    return patch.object(owner, name, observed)
class Case(CleanupOwnershipTests):
    def setUp(self):
        emit('setup_begin'); super().setUp(); emit('setup_end')
    def assertGreater(self, a, b, msg=None):
        if msg == 'must preserve useful exports': emit('useful_export', exported=a)
        return super().assertGreater(a, b, msg)
    def tearDown(self):
        emit('teardown_begin'); super().tearDown(); emit('teardown_end')
if __name__ == '__main__':
    done = threading.Event()
    threading.Thread(target=watchdog, daemon=True).start()
    try:
        with forward(gt._Engine, '_client'), forward(gt.PooledSession, 'post'), forward(ot.OTLPExporter, '_send'):
            result = unittest.TextTestRunner(verbosity=2).run(Case('test_global_reserve_drains_late_final_batch_retirement'))
        print('EXPORT_PHASE ' + json.dumps(rows), flush=True)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    finally:
        done.set()
