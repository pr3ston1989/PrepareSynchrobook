# Nokturn synchrobook interchange v1

`GET /api/synchrobooks/capabilities` requires an administrator and reports `schema=1`, `existing_epub_only=true`. External tools use a scoped key in `Authorization: Bearer nk_sync_…`. Create/revoke keys locally on the server with `manage_synchrobook_api_keys.bat`, or use account-authenticated `GET/POST /api/synchrobook-keys` and `DELETE /api/synchrobook-keys/{id}`. POST accepts `{"name":"PrepareSynchrobook","days":90}` and returns the clear key once. These management endpoints require an administrator account session; a scoped key cannot create another key. Keys expire within 1–365 days and are invalidated by revocation, owner role removal, owner deletion or account session-version reset. Only SHA-256 digests of cryptographically random secrets are stored. Never persist the key in a project. Existing administrator JWT sessions remain compatible with the synchrobook endpoints, but the external tool does not ask for account credentials.

- `GET /api/synchrobooks/books?q=…`: up to 100 visible, available audiobooks.
- `GET /api/synchrobooks/{id}/epub`: original EPUB already associated with that audiobook. Does not generate or modify the publication.
- `POST /api/synchrobooks/{id}/import?reviewed=true`: raw `application/zip`, max 64 MiB. The ZIP contains **only `manifest.json`**. No EPUB or audio is uploaded.

Manifest fields:

```json
{
  "format": "nokturn-synchrobook",
  "schema": 1,
  "generator": "PrepareSynchrobook/0.1.0",
  "text_source": "existing-epub",
  "title": "Title",
  "author": "Author",
  "language": "pl",
  "epub_sha256": "full-original-file-sha256",
  "audio_files": [
    {"name": "01.mp3", "bytes": 1234, "sha256": "full-audio-file-sha256", "duration_sec": 60.0}
  ],
  "timestamps": [
    {"chapter_idx": 1, "para_idx": 0, "start_sec": 2.0, "end_sec": 8.0,
     "confidence": 0.95, "interpolated": false, "sentences": [[0, 42, 2.0, 0.95]]}
  ]
}
```

Hash values in this example are placeholders; actual values are 64 lowercase hexadecimal characters. Audio files are ordered exactly as Nokturn's natural filename ordering. Times are seconds on the **whole audiobook** timeline, including silence and any non-speech portions. EPUB spine chapter order and audio file order are independent.

`chapter_idx` is a zero-based EPUB document index in Nokturn spine order; `para_idx` is the zero-based index among **all** `<p>` tags in that document. Text is normalized with `re.sub(r"\s+", " ", p.get_text()).strip()`. Sentence tuples contain `[charStart, charEnd, audioStartSeconds, confidence]`, where character offsets are JavaScript UTF-16 code units, not Python Unicode code point counts. End offsets are exclusive. A paragraph may have no reliable sentence anchors; paragraph-level timing remains usable. Unmatched EPUB paragraphs are omitted rather than assigned invented times.

Nokturn compares the existing EPUB hash, ordered full audio hashes, sizes and durations; validates paragraph/sentence ranges and monotonic positions; then updates synchronization and source provenance in one transaction. Original publication paths, EPUB bytes, audio, reading/listening progress and preferences remain untouched. Import and local recognition share a per-book lock. Audio hashing does not hold a database connection. Error 409 indicates changed sources/conflict; 422 an invalid package; 403 insufficient permissions. Retrying an identical valid package is safe.
