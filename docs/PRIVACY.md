# Privacy and data flow

Browser → local HTTP adapter → bounded parser → deterministic catalog → PDF renderer → bounded in-memory token store. No outbound request, account, analytics, model, or original-evidence persistence exists in the default build.

Scanner exports can contain private URLs, query parameters, DOM text, selectors, internal hosts, names, email addresses, screenshots or accidentally captured credentials. Users must sanitize evidence before public-demo or issue submission. Never place real evidence in GitHub issues or automation prompts.

Default retention is up to 30 minutes in process memory. Reports can be removed earlier when the item or byte quota is reached; process restart removes all reports. The default store retains at most 100 reports and 50,000,000 combined PDF, HTML and receipt bytes per process. Each report must fit that same byte budget; quota rejection does not delete existing reports. Required storage initialization fails startup rather than installing a fake store.

Operators changing storage, telemetry, authentication, sharing or hosting must create a new data-flow assessment, privacy notice, retention schedule, deletion process, access controls and incident plan.
