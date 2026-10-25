# Ingress SSO verification

## Automated checks

```sh
python -m pip install -r calibre-web-automated/tests/requirements.txt
python -m unittest discover -s calibre-web-automated/tests -v
```

These exercise the add-on adapter with Flask, HTTP Basic authentication,
CSRF and SQLite. They do not boot the full CWA application or Supervisor.
The Linux workflow additionally checks nginx's actual trust boundary and
shell syntax. A separate root-run regression reproduces Supervisor's
root-only `options.json` permissions and verifies that the launcher reads
options before dropping UID, GID and supplementary groups. CWA is imported
only after this privilege change. The CWA source version remains v4.0.6.

## Build and HAOS acceptance (required before upstream submission)

Use a test installation and back up the installed add-on first. This branch
does not bump the stable version: it is intended for a local test build.
Copy this branch's `calibre-web-automated` directory into HA's local add-ons
directory (`/addons`), refresh the store, and install the local add-on. A
local installation has its own private state; it does not adopt the installed
repository add-on's private database. If already testing a local copy, use
Supervisor's rebuild action after replacing its files. Check build/start logs.

1. With SSO disabled, set up the library and a CWA administrator. Confirm
   password login, a restart, book viewing/download and optional direct access.
   Record the exact CWA admin name and test its password.
2. Leave the host port for 8083 unset. Enable SSO with your HA **user ID**
   in `admin_users`, your CWA admin in `admin_account`, and
   `auto_create_users: true`. Restart. Opening CWA through HA must show the
   selected admin without another login. Check static files, redirects,
   uploads and an operation that submits a CSRF-protected form.
3. Use a separate HA browser session with another HA user who is allowed to
   open this add-on. Confirm a separate `ha_<ID>` account, reading/download
   access and denied admin/edit/delete/upload operations. Restart; the same
   account and reading state must remain. Rename this HA user; it must retain
   its own CWA identity. Test switching HA users in the same browser as well.
4. Disable automatic creation. An existing bound reader must still work;
   an unseen HA user must receive HTTP 403. Remove an ID from `admin_users`
   and restart; that ID must no longer reach the CWA admin account.
5. From another container/add-on and from the LAN, attempt ports 8083 and
   8084, including forged `X-Remote-User-Id`, `X-CWA-Ingress` and
   `X-Forwarded-For` headers. Port 8083 must not accept network connections;
   nginx on 8084 must deny non-Supervisor sources. Temporarily map 8083 on
   the test installation and confirm it still cannot reach CWA with SSO on.
   Remove the mapping afterward. Confirm the listener inside the container
   is `127.0.0.1:8083`, not `0.0.0.0:8083` or `[::]:8083`.
6. Check missing/invalid identity headers at the trusted proxy path: access
   must fail even with a previous CWA admin cookie or Basic credentials.
   OAuth, Magic Links, Kobo and KOReader sync must be denied in SSO mode.
7. Set an invalid/non-admin `admin_account` with an allowlisted ID: CWA must
   fail to start. Correct the option and restart to recover.
8. Disable SSO and restart. Confirm the original CWA admin password still
   works and optional direct access is restored. Confirm saved login settings,
   existing account roles and library data were not changed by SSO.

Record HAOS, Supervisor, architecture, build result and each acceptance
result in the draft PR. The upstream PR should remain unsubmitted until
the container build and these live checks pass. A release version/changelog
can be agreed with the upstream maintainer after testing.
