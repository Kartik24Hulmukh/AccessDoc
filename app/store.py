from __future__ import annotations
from dataclasses import dataclass
from threading import RLock
from time import monotonic
import secrets
from .limits import LimitExceeded
from .store_expiry import SCHEDULER

@dataclass(frozen=True)
class StoredReport:
    pdf: bytes
    html: bytes
    receipt: bytes
    filename: str
    created_at: float

class TTLReportStore:
    def __init__(self,ttl_seconds:int=1800,max_items:int=100,max_bytes:int=50_000_000):
        if ttl_seconds <= 0 or max_items < 1 or max_bytes < 1:raise ValueError("Store limits must be positive")
        self.ttl_seconds=ttl_seconds; self.max_items=max_items; self.max_bytes=max_bytes
        self._items:dict[str,StoredReport]={}; self._bytes=0; self._lock=RLock();self.closed=False
    @staticmethod
    def _size(item:StoredReport)->int:return len(item.pdf)+len(item.html)+len(item.receipt)
    def _remove(self,key):
        item=self._items.pop(key,None)
        if item:self._bytes-=self._size(item)
    def _purge(self,now=None):
        now=monotonic() if now is None else now
        for key,item in list(self._items.items()):
            if now-item.created_at>=self.ttl_seconds:self._remove(key)
        while len(self._items)>self.max_items or self._bytes>self.max_bytes:
            if not self._items:break
            self._remove(min(self._items,key=lambda k:self._items[k].created_at))
    def put(self,pdf:bytes,html:bytes,receipt:bytes,filename:str)->str:
        size=len(pdf)+len(html)+len(receipt)
        # One coherent operator quota bounds both each complete report and the
        # retained process total. Hidden per-format ceilings rejected valid
        # findings long before this budget, especially receipts above 100 KiB.
        if size>self.max_bytes:
            raise LimitExceeded('Generated output exceeds store capacity',
                                limit_name='REPORT_MAX_BYTES',
                                limit=self.max_bytes,actual=size)
        with self._lock:
            if self.closed:raise RuntimeError("Report store is closed")
            self._purge();token=secrets.token_urlsafe(24);item=StoredReport(bytes(pdf),bytes(html),bytes(receipt),str(filename),monotonic())
            self._items[token]=item;self._bytes+=self._size(item);self._purge();self._schedule();return token
    def _schedule(self):
        deadline=min((item.created_at+self.ttl_seconds for item in self._items.values()),default=None)
        SCHEDULER.schedule(self,deadline)
    def _expire(self):
        with self._lock:
            if self.closed:return
            self._purge();self._schedule()
    def close(self):
        with self._lock:
            self.closed=True;self._items.clear();self._bytes=0;SCHEDULER.schedule(self,None)
        SCHEDULER.wait_idle()
    def get(self,token:str)->StoredReport|None:
        with self._lock:
            self._purge();item=self._items.get(token)
            return StoredReport(item.pdf,item.html,item.receipt,item.filename,item.created_at) if item else None
    @property
    def stats(self):
        with self._lock:
            self._purge();return {'items':len(self._items),'bytes':self._bytes}
