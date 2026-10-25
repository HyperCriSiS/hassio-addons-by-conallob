# Home Assistant Add-on: Calibre-Web Automated

## Overview

Calibre-Web Automated (CWA) manages a Calibre library through a web UI and
automates the boring parts: drop a book into a watched ingest folder and it
gets converted, added to the library, checked for a cover, and (optionally)
converted to Kepub for Kobo sync — no manual `calibredb` or Calibre-Web admin
steps required.

The add-on's version tracks the upstream [Calibre-Web Automated release](https://github.com/crocodilestick/Calibre-Web-Automated/releases)
it bundles one-to-one — check `config.yaml`'s `version` (or `build.yaml`'s
`CWA_VERSION` for the exact git tag fetched at build time) to see which CWA
release is currently packaged.

This add-on runs the upstream CWA application, the real Calibre binaries and
kepubify unmodified; only the surrounding container (base image, init
scripts, volume layout) is adapted for Home Assistant's Supervisor and
s6-overlay conventions.

On first start, CWA creates its own SQLite databases (`app.db`, `cwa.db`) and
prompts you to create an admin account the first time you open the web UI —
there's no add-on option for that.

---

## Options

### Option: `library_dir`

Path, relative to `/share`, where the Calibre library lives. Created
automatically if it doesn't exist. Point this at an existing library to
import it as-is.

Default: `calibre-web-automated/library`

### Option: `ingest_dir`

Path, relative to `/share`, that CWA watches for new ebooks to
automatically import. Drop a supported file (EPUB, MOBI, AZW3, PDF, CBZ/CBR,
and others) in here via Samba/the File editor add-on and CWA picks it up
within seconds.

Default: `calibre-web-automated/ingest`

### Option: `network_share_mode`

Set this to `true` if `/share` is itself a network mount (NFS/SMB) on your
Home Assistant host. `inotify`-based file watching is unreliable over
network filesystems, so this switches the ingest watcher and metadata change
detector to a polling fallback instead, and skips `chown`-ing files it
doesn't need to touch on the mount.

Default: `false`

### Option: `sso`

Optional Home Assistant ingress-only authentication. Disabled by default;
upgrading does not change the existing login or optional direct access.

```yaml
sso:
  enabled: true
  admin_users:
    - "0123456789abcdef0123456789abcdef"
  admin_account: "admin"
  auto_create_users: true
```

- `enabled`: authenticate every request exclusively through HA ingress.
  CWA then binds to `127.0.0.1:8083`; even a configured host port mapping
  cannot expose that backend. Leave the optional network port unset.
- `admin_users`: **Home Assistant user IDs, not usernames or display names**.
  Find the ID in the user's detail view under Settings → People → Users
  (advanced mode may be needed). The ID is 32 lowercase hexadecimal characters.
  Supervisor supplies it as `X-Remote-User-Id`. IDs keep the binding stable
  across renames and avoid granting access when a username is reused.
  `X-Remote-User-Name` is deliberately not an authorization key.
- `admin_account`: exact name of an **existing CWA administrator**. All
  allowlisted HA IDs use this account. SSO does not create/promote this admin;
  an invalid target prevents startup. Configure it with SSO disabled first.
  Multiple allowlisted IDs share this account's library settings and history.
- `auto_create_users`: create separate accounts for other authenticated HA IDs.
  These start with reading/download rights only, regardless of CWA's default
  new-user role. No admin, upload, delete, edit or password-change permissions
  are granted automatically. Accounts are named `ha_<HA user ID>` and retain
  their identity after HA username/display-name changes. CWA's default content
  restrictions are copied at creation. Existing local accounts are never
  adopted just because their names match. Bindings persist in the
  `ha_ingress_users` table in `app.db`. When false, only already bound users
  and allowlisted admins can sign in. Removing an admin ID takes away its
  admin mapping after restart. A regular bound account manually promoted to
  CWA admin is denied; grant admin access through the allowlist instead.

The ingress listener accepts connections only from Supervisor's documented
gateway address `172.30.32.2`, in both login modes. SSO requires a Supervisor
that sends `X-Remote-User-Id`; missing/invalid IDs are denied, including for
previously authenticated CWA sessions. There is no fallback to a password,
remember-me cookie, username header, or anonymous browsing. The adapter uses
the pinned CWA version's login hooks; upgrading CWA requires retesting them.

In SSO mode, OAuth, Magic Links, Kobo sync and KOReader sync endpoints are
blocked because they carry separate identities. OPDS through an authenticated
HA ingress session uses the HA identity, even when Basic credentials are
supplied; standalone readers cannot authenticate through ingress. Use the
normal login mode if external devices/direct OPDS are required. CWA logout
does not log out of HA; the next ingress request authenticates again.

To return to normal CWA login, set `sso.enabled: false` and restart the add-on.
The adapter does not change saved CWA login settings, passwords or existing
roles. Keep an independently tested CWA admin password and an add-on backup.
Automatically created accounts and their bindings remain when SSO is disabled.

---

## Volumes

CWA's own app state (`app.db`, `cwa.db`, conversion temp files, etc.) lives
under the add-on's private, persistent `/data` volume — not under `/share`
or Home Assistant's own `/config` — since it's internal application state,
not something to browse or edit directly. The library and ingest folders
above are the two paths you're expected to interact with, both under
`/share` so they're reachable from other add-ons (e.g. Samba) too.

| Container path | Backed by |
|---|---|
| `/config` (CWA's own, not HA's) | `/data/config` |
| `/calibre-library` | `/share/<library_dir>` |
| `/cwa-book-ingest` | `/share/<ingest_dir>` |

## Ports

| Port | Purpose |
|------|---------|
| 8083 | CWA web UI; loopback-only while SSO is enabled, otherwise optionally mappable |
| 8084 | Ingress-only reverse proxy in front of 8083 (internal; not mapped) |

## Known limitations

- **RAR/CBR extraction**: full RAR5 support requires the proprietary `unrar`
  binary, which isn't packaged for Debian. The build falls back to
  `unrar-free` (RAR3-era support only) when available; older or RAR5-format
  `.cbr`/`.rar` files may fail to extract.
- **Kernel/Qt6 compatibility**: CWA's own `cwa-init` service checks the host
  kernel version and strips Qt6 ABI tags on very old kernels (pre-6.0) to
  keep PDF/WebEngine features working; this is unchanged from upstream.
- This add-on has not yet been build- or run-tested against a live
  Supervisor install — see the README for details.

## Upstream documentation

- [Home Assistant ingress requirements](https://developers.home-assistant.io/docs/apps/presentation/#ingress)
- [Supervisor ingress identity headers](https://github.com/home-assistant/supervisor/blob/main/supervisor/api/ingress.py)
- [Calibre-Web Automated wiki](https://github.com/crocodilestick/Calibre-Web-Automated/wiki)
- [Calibre-Web Automated README](https://github.com/crocodilestick/Calibre-Web-Automated#readme)
