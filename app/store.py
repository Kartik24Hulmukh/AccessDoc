from __future__ import annotations
from dataclasses import dataclass
from threading import RLock
from time import monotonic
import secrets

@dataclass(frozen=True)
class StoredReport:
    pdf: bytes
    html: bytes
    receipt: bytes
    filename: str
    created_at: float

class TTLReportStore:
    def __init__(self,ttl_seconds:int=1800,max_items:int=100,max_bytes:int=50_000_000):
        self.ttl_seconds=ttl_seconds; self.max_items=max_items; self.max_bytes=max_bytes
        self._items:dict[str,StoredReport]={}; self._bytes=0; self._lock=RLock()
    @staticmethod
    def _size(item:StoredReport)->int:return len(item.pdf)+len(item.html)+len(item.receipt)
    def _remove(self,key):
        item=self._items.pop(key,None)
        if item:self._bytes-=self._size(item)
    def _purge(self,now=None):
        now=monotonic() if now is None else now
        for key,item in list(self._items.items()):
            if now-item.created_at>=self.ttl_seconds:self._remove(key)
        while len(self._items)>=self.max_items or self._bytes>self.max_bytes:
            if not self._items:break
            self._remove(min(self._items,key=lambda k:self._items[k].created_at))
    def put(self,pdf:bytes,html:bytes,receipt:bytes,filename:str)->str:
        if len(pdf)>10_000_000 or len(html)>5_000_000 or len(receipt)>100_000:raise ValueError('Generated output exceeds storage limit')
        with self._lock:
            self._purge();token=secrets.token_urlsafe(24);item=StoredReport(bytes(pdf),bytes(html),bytes(receipt),str(filename),monotonic())
            self._items[token]=item;self._bytes+=self._size(item);self._purge();return token
    def get(self,token:str)->StoredReport|None:
        with self._lock:
            self._purge();item=self._items.get(token)
            return StoredReport(item.pdf,item.html,item.receipt,item.filename,item.created_at) if item else None
    @property
    def stats(self):
        with self._lock:
            self._purge();return {'items':len(self._items),'bytes':self._bytes}
