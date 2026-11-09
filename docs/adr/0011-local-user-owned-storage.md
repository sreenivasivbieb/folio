# 0011 — User-owned local storage, optional user-owned connections

The user requires working data to remain on each user's own machine, with no central
Folio database or cloud account. Local and hosted AI remain choices using the user's own
credentials. Google Drive backup is an explicit optional user connection.

Replace MongoDB and its Docker dependency with local `knowledge.sqlite3`, retaining real
transactions for ledger/import atomicity. Keep the rebuildable SQLite search/job index.
Credentials remain in a separate private local file and are excluded from exports.

Package the UI and Python core for Omarchy so runtime paths do not depend on a checkout.
Offer computer/drive scanning, metadata inventory and exclusion controls. Backup JSON may
be copied explicitly to Google Drive through the user's Desktop OAuth app, using a local
PKCE callback and drive.file scope; no developer credentials or relay are provided.

This supersedes ADR-0009's MongoDB deployment requirement. Existing exports remain
importable, and old containers/volumes are neither deleted nor migrated automatically.
