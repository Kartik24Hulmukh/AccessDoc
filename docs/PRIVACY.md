# Privacy and data flow

Browser → local HTTP adapter → bounded parser → deterministic catalog → PDF renderer → bounded in-memory token store. No outbound request, account, analytics, model, or original-evidence persistence exists in the default build.

Scanner exports can contain private URLs, query parameters, DOM text, selectors, internal hosts, names, email addresses, screenshots or accidentally captured credentials. Users must sanitize evidence before public-demo or issue submission. Never place real evidence in GitHub issues or automation prompts.

Default retention is 30 minutes in process memory. Process restart removes reports. Operators changing storage, telemetry, authentication, sharing or hosting must create a new data-flow assessment, privacy notice, retention schedule, deletion process, access controls and incident plan.
