# Hazel HTTP Bridge (PC-Free)

This is an optional remote component for Hazel. It accepts BitTorrent magnet links on a machine where torrent use is permitted, downloads into an isolated per-job folder, and serves completed files over an authenticated HTTP API. Hazel can then fetch the result using its normal HTTPS/direct-download path.

## Security and network policy

- Use only content you are authorized to download.
- Run this bridge only on a host/network where BitTorrent use is permitted. It is not intended to bypass an employer's network controls.
- The Compose file binds to `127.0.0.1:8787` by default. Do not expose port 8787 directly to the public Internet.
- For access from a phone, deploy behind a properly configured HTTPS reverse proxy or private access gateway, with TLS and access controls. Do not use plaintext HTTP across untrusted networks.
- Use a random token of at least 32 characters. Anyone who obtains the token can submit jobs and download files.
- Job metadata is persisted atomically to a dedicated `/state` volume. Completed jobs and files survive a container restart. Active jobs interrupted by a restart are marked failed with a clear message; submit the magnet again to resume.
- A completed multi-file torrent exposes each file separately. There is no archive packaging in this initial version.

## Run with Docker Compose

From this directory:

```sh
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Put the generated value in .env as BRIDGE_TOKEN=...
docker compose up --build -d
curl http://127.0.0.1:8787/health
```

The health endpoint is unauthenticated and returns only service status. All job endpoints require a bearer token.

## API

Set `TOKEN` to the same value as `BRIDGE_TOKEN`.

Create a job:

```sh
curl -X POST http://127.0.0.1:8787/api/v1/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"magnet_uri":"magnet:?xt=urn:btih:REPLACE_WITH_A_VALID_INFO_HASH"}'
```

The response contains a job `id` and status. Poll `GET /api/v1/jobs/{id}` until status is `complete`, then read the returned relative `files` list and fetch a selected file:

```sh
curl -H "Authorization: Bearer $TOKEN" \
  -OJ "http://127.0.0.1:8787/api/v1/jobs/JOB_ID/files/relative/path/file.ext"
```

Other endpoints:
- `GET /api/v1/jobs` — list persisted jobs
- `DELETE /api/v1/jobs/{id}` — cancel a job
- `GET /health` — health check

Only `magnet:` links with a BitTorrent info hash are accepted. Arbitrary URL downloads are deliberately not accepted by the torrent worker to reduce SSRF risk.

## Current prototype limitations

- The worker needs `aria2c` and outbound peer connectivity on the remote host.
- Active peer transfers are not automatically resumed after a process restart; their saved job is marked interrupted so the user can resubmit the magnet.
- Storage quota is a coarse guard, not a hard per-job limit.
- HTTP API requests require a bearer token; use HTTPS when crossing networks.
- Hazel Android UI/client integration is being built in its companion pull request. A passing build is not the same as an end-to-end physical-device transfer test.
