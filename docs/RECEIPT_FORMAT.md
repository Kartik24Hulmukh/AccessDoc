# Input receipt format

The JSON sidecar identifies the submitted UTF-8 text and generated PDF by SHA-256. It records adapter, generator, catalog, mapping counts, and whether manual findings were supplied.

It does not authenticate the submitter or source, prove completeness or accuracy, establish chain of custody, or determine accessibility conformance.

## Offline verification

```bash
python scripts/verify_receipt.py receipt.json submitted-input.txt report.pdf
```

Use the exact UTF-8 text submitted to the API. Browser file decoding or newline conversion can make an original file differ from the submitted text; that difference must not be described as tampering.
