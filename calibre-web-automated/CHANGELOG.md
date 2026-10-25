# 4.0.6.2

- Automatically map Home Assistant administrators to the configured CWA
  administrator when `sso.admin_users` is empty. No user ID needs to be copied.
- Keep separate reader accounts for normal HA users and allow them to open
  the add-on panel. Roles come from Supervisor's trusted group header;
  missing or malformed groups never grant administrator rights.
- Preserve nonempty ID lists as an explicit selection on upgrade. Replace
  an old list with `admin_users: []` and restart to enable automatic roles.
- Add regression coverage for role revocation, group parsing, explicit list
  compatibility and proxy forwarding. Upstream CWA remains v4.0.6.

# 4.0.6.1

- Identify this branch as **Calibre-Web Automated (HyperCriSiS SSO Test)**
  in the store and **CWA - HyperCriSiS SSO Test** in the sidebar.
- Use **HyperCriSiS Add-ons (SSO Test)** as the repository name and link
  to the test branch.
- Include optional ingress SSO and the Supervisor options permission fix:
  read protected options before dropping to the application user.
- Keep upstream CWA at v4.0.6. The final version component is the add-on
  revision, allowing existing branch installations to receive an update.
