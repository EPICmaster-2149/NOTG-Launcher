# NOTG Launcher error codes

Every warning or critical error dialog uses the shared presenter in
`app/ui/errors.py`. The dialog intentionally shows a short explanation,
an action to try, and one code. Raw Python exceptions, terminal colour
sequences, file paths, tokens, and URLs are not shown to players.

Information and confirmation dialogs are not failures and do not receive an
error code. Status text inside a page is likewise not a modal error dialog.

## Music

| Code | User meaning | Likely technical cause | Developer checks |
| --- | --- | --- | --- |
| `ERR-MUS-001` | Music is already being prepared. | More than one online-audio resolver attempted to use the same source-hash cache name, or a previous process still holds a yt-dlp `.part` file. | Confirm `MusicController._stream_resolution_sources` blocks duplicate refreshes. Check for another launcher process and stale files in `music-stream-cache`. |
| `ERR-MUS-002` | The online track is temporarily unavailable. | The remote provider rejected the request, commonly YouTube HTTP 403, expired media data, region restrictions, a private video, or provider-side rate limiting. | Update yt-dlp/EJS, inspect sanitized resolver output, and verify public playback in a browser. Do not expose request headers or signed URLs to users. |
| `ERR-MUS-003` | The online music link could not be prepared. | yt-dlp is missing/outdated, no supported audio format was returned, the URL is invalid, or the local music cache cannot be created. | Verify bundled dependencies, Node/EJS availability where needed, selected format support, write access, and source metadata. |

## Files, network, and launcher operations

| Code | User meaning | Likely technical cause | Developer checks |
| --- | --- | --- | --- |
| `ERR-FILE-001` | The launcher cannot access a required file. | Windows sharing violation, antivirus scan, insufficient permissions, or another application holding a file. | Identify the process using the file; retry after it releases. Prefer unique temporary names and atomic replacement for writes. |
| `ERR-NET-001` | A network request could not be completed. | Offline connection, DNS/TLS failure, timeout, proxy/firewall, or remote service outage. | Record the endpoint/status in diagnostic logs without leaking credentials; retry with bounded backoff. |
| `ERR-INS-001` | The Minecraft instance operation could not be completed. | Invalid install selection, missing game files, disk-space issue, archive failure, or launcher process failure. | Inspect installer/launch log, Java selection, target folder, and available disk space. |
| `ERR-MOD-001` | The mod or modpack operation could not be completed. | Provider/API error, incompatible Minecraft or loader version, bad archive, or mod file conflict. | Verify version compatibility, Modrinth response, archive integrity, and install logs. |
| `ERR-ACC-001` | The account operation could not be completed. | Authentication expired, OAuth callback problem, invalid account state, or service/network failure. | Verify redirect configuration and account credentials; never place tokens in the dialog or logs. |
| `ERR-JAVA-001` | Java needs attention. | Java is missing, unsupported for the chosen Minecraft version, or configured path is invalid. | Check discovered runtimes and the Java compatibility rule for the selected version. |
| `ERR-UPD-001` | The update operation could not be completed. | Update manifest/download failed, downloaded package is invalid, or updater cannot replace an in-use file. | Check updater log, package signature/layout, target permissions, and whether launcher files are locked. |

## Fallback

| Code | Meaning | Developer action |
| --- | --- | --- |
| `ERROR-404` | An unclassified internal error reached a user-facing dialog. | Treat this as a classification gap: reproduce the action, inspect the original exception in diagnostics, then add a specific rule to `present_error` and this document. |

## Error-dialog contract

`ui.errors.QMessageBox` is a facade for all UI modules that display static
`warning` or `critical` dialogs. It preserves standard confirmation dialogs
(`question`) and non-error notices (`information`). New UI code must import
`QMessageBox` from `ui.errors`, not from `PySide6.QtWidgets`, whenever it
shows a warning or critical error. This ensures unknown errors use `ERROR-404`
instead of exposing implementation details.
