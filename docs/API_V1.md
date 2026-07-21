# API v1

`POST /api/v1/generate` accepts `application/json` with `scanner_input` plus optional `format_hint`, client/agency names, date, primary color, PNG data URL, and manual findings. Success is `201` with a temporary download URL, normalized counts, detected format, catalog-review count, and expiry. Validation failures are `422`; cross-site requests `403`; rate limits `429`; capacity `503`. Every response carries `X-Request-ID`.

Compatibility: additive response fields are allowed in v1; existing fields and meanings are not removed or changed without a new major API path. `/api/generate` is a compatibility alias during 0.x.
