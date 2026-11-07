# @folio/api-client

`src/schema.d.ts` and `openapi.json` are **generated** from the core (`npm run gen:client` at the
repo root). Do not edit them by hand; CI fails if they are stale. `src/index.ts` adds a small
`createFolioClient(connection)` wrapper (openapi-fetch) and friendly type aliases.
