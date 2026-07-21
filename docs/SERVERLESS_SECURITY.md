# Serverless security and privacy boundary

The Vercel adapter is stateless: it accepts bounded JSON, generates PDF/HTML/receipt/manifest bytes in one invocation, and returns one ZIP. Fixed archive member names prevent uploaded paths from becoming ZIP paths. Responses are attachment-only and carry browser, CDN, and Vercel-CDN no-store headers. Source evidence, client names, filenames, hashes, tokens, and generated artifacts are not logged by the adapter.

The repository does not provide distributed abuse control. Before any anonymous hosted use, add authentication or invite gating, Vercel Firewall rate limits, spend alerts, an operator kill switch, protected previews, deployed log-canary tests, and independent application-security/privacy review. Do not operate an unrestricted public upload service from repository evidence alone.

Generated PDFs are untagged and are not claimed as PDF/UA. The semantic HTML companion is not a WCAG conformance claim. AccessDoc normalizes supplied evidence and does not rescan or authenticate the source.
