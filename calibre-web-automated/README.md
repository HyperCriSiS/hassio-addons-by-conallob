# Calibre-Web Automated (HyperCriSiS SSO Test)

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

[Calibre-Web Automated](https://github.com/crocodilestick/Calibre-Web-Automated)
(CWA) is a self-hosted ebook library manager: a Calibre-Web fork with a
watched ingest folder, automatic format conversion, cover/metadata
enforcement and Kepub conversion for Kobo devices, wrapped around a Calibre
library.

This is HyperCriSiS's experimental SSO test build, based on Conall O'Brien's
add-on. Add-on version `4.0.6.1` packages upstream CWA `v4.0.6`; the final
version component identifies the add-on revision. See `build.yaml`'s
`CWA_VERSION` for the upstream source version.

## About

Optional Home Assistant ingress SSO can map selected HA user IDs to an
existing CWA administrator and provision separate reader accounts. It is
disabled by default. See [SSO configuration and limitations](DOCS.md#option-sso)
and the [HAOS test checklist](TESTING.md) before enabling it.

CWA bundles a real Calibre install, [kepubify](https://github.com/pgaskin/kepubify)
and several background workers (ingest watcher, metadata change detector,
nightly library zipper, checksum backfill, process recovery) on top of the
Calibre-Web Flask app. Upstream distributes it as a single Docker image built
on `ghcr.io/linuxserver/baseimage-ubuntu`. This add-on instead builds those
same pieces — the CWA application, Calibre, and kepubify — directly on the
official Home Assistant Debian base image, fetching each from its own
upstream source rather than using a third-party image as the base.

Because it reassembles a fairly large upstream project (Calibre plus a full
Python/Flask app plus several s6 services) rather than a single static
binary, this is a best-effort initial port: it has not been build- or
run-verified against a live Supervisor install. Please open an issue with
build/runtime logs if something doesn't come up cleanly.

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
