# Security Policy

## Supported deployment

StratWeb 0.4.x is a local-first offline analyzer. The supported HTTP deployment binds to
`127.0.0.1`. Docker Compose also publishes port 8000 on host loopback only.

The application has no user authentication or tenant authorization. Do not expose it
through a public reverse proxy, tunnel, router port-forward or an untrusted LAN. A proxy
can make a remote request appear to originate from loopback, so localhost mutation guards
are not a replacement for authentication.

## Sensitive local data

Demo files, Steam IDs, server names, original filenames, DuckDB databases, `.env` files,
generated reports and locally extracted Valve map assets must remain outside version
control. Backups should be protected like the original files.

## Reporting a vulnerability

Until a private security contact is configured, do not open a public issue containing a
demo, Steam ID, database, credentials or another user's data. Record a minimal local
reproduction without private artifacts and contact the repository owner directly.

## Out of scope

StratWeb must not add live match assistance, memory reading, game injection, input
automation or other cheating functionality.
