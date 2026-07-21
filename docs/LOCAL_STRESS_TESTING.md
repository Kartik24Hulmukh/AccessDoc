# Local stress testing

Start the service with conservative defaults, then run supported and overload phases:

```bash
python -m app.main
python scripts/stress_test.py --workers 2 --requests 200
python scripts/stress_test.py --workers 64 --requests 400
```

Expected outcomes are complete 201 responses under admitted load and explicit 503 responses under overload. Transport resets, 500 responses, cross-report leakage, unbounded error counters, failed TTL reclamation, or inability to recover after a slow client are release blockers.

The checked-in evidence reflects one local machine. It is not a capacity promise for another host or proof of hosted-service reliability.
