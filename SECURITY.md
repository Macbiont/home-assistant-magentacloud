# Security policy

Please do not publish credentials, backup archives, diagnostic downloads, or
complete Home Assistant logs in an issue.

For a suspected vulnerability, use GitHub's private vulnerability reporting
feature for this repository. For ordinary bugs, open a regular issue with
secrets and personal data removed.

MagentaCLOUD credentials are stored by Home Assistant in the integration's
config entry. Use a dedicated WebDAV session password and revoke it immediately
if it may have been exposed.
