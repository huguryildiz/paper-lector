# Security

Report a vulnerability privately through GitHub's "Report a vulnerability" button on the repository's Security tab (https://github.com/huguryildiz/paper-lector/security/advisories/new), not in a public issue. Say which script and version, and how to reproduce it. If that button is not shown, open an issue that says only that you have a security report, with no details, and the author will reply with a private channel.

What paper-lector guards, and what it does not, is in [`REFERENCE.md`](REFERENCE.md#safety). In short:

- `fetch_pdf.py` fetches only http(s) URLs on public addresses and checks every redirect; a DNS answer that changes between the check and the connection is not covered.
- API keys go only into request headers, never into logs, CSVs or run records.
- `literature.json` and the `sources` CSV are trusted: their paths can name any file. Do not run the scripts on a project config you have not read.
