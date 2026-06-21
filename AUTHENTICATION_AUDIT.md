# Authentication Audit

## Findings

- Microsoft login currently defaults to `https://login.live.com/oauth20_desktop.srf`. That redirect is a legacy desktop completion page, so the launcher can only finish by asking the user to copy a URL. This is why users see an "applications" page and the flow fails when the callback is not captured automatically.
- The configured Microsoft application is returning `AADSTS90023`, which means authorization codes are being issued for a Single Page Application redirect type. Microsoft rejects redeeming those codes from native/Python code without a browser `Origin` header. The launcher now retries token redemption with a SPA-compatible `Origin` header when this exact provider error appears.
- The embedded redirect page can still show Microsoft's "This is not the right page" and can trigger duplicate/expired-code failures. The normal launcher UI now uses the same user-facing pattern as Prism-style launchers: show `https://www.microsoft.com/link`, show the device code, and poll the token endpoint while the user signs in through their regular browser.
- Microsoft authentication should use authorization code flow with PKCE, preserve and validate `state`, then exchange the code with the same redirect URI used for authorization before continuing through Xbox Live, XSTS, Minecraft services, and profile retrieval.
- For an embedded Microsoft WebEngine flow, Microsoft documents `https://login.microsoftonline.com/common/oauth2/nativeclient` as the native redirect value. For system-browser fallback, loopback redirects such as `http://localhost` are the modern pattern and can be captured by a local listener without copy/paste.
- The existing UI has an embedded web view, but the code bypasses it whenever the redirect is not loopback by opening the system browser and showing a paste dialog. That makes the embedded window mostly cosmetic for the default Microsoft redirect.
- Ely.by OAuth documentation uses `client_id`, `redirect_uri`, `response_type`, `scope`, and `state` for authorization initiation, and `client_id`, `redirect_uri`, `grant_type`, and `code` for token exchange. The token exchange can include `client_secret` only when one exists; this launcher's `notg-launcher` client is public and must not fabricate a secret.
- Ely.by's live authorization page currently rejects the snake_case authorize parameters with `Invalid request (null required)`. The launcher therefore uses Ely.by's documented table/client field names for the browser leg (`clientId`, `redirectUri`, `responseType`) and the documented snake_case names for the token endpoint.
- Ely.by also documents a launcher-specific Yggdrasil-compatible auth server at `https://authserver.ely.by`. Because the project only has public client id `notg-launcher` and no Ely.by client secret, the launcher UI now defaults to Ely.by launcher authentication (`/auth/authenticate`) instead of the OAuth page. This avoids the hanging OAuth web registration path while still receiving an `accessToken` with `minecraft_server_session` rights.
- Ely.by launcher sessions should request `minecraft_server_session` in addition to `account_info` and `offline_access`, otherwise the OAuth access token may not be suitable as a Minecraft session token.
- Account storage already supports multiple typed accounts, per-account tokens, UUIDs, skins, capes, active account selection, and refresh. The redesign should preserve that schema and improve the login/callback/refresh edges rather than replacing account storage.

## Implementation Direction

- Remove manual URL/code paste from OAuth completion.
- Use Microsoft device authorization as the default launcher flow, shown as a Prism-style link/code panel. If the configured Microsoft app registration rejects device token redemption, report that the Azure app must allow public client flows or be replaced with a Minecraft-approved public/native app client ID.
- Keep embedded Microsoft OAuth with PKCE as service support code only; if Microsoft returns `AADSTS90023`, retry token redemption with a SPA-compatible `Origin` header.
- Prefer embedded completion when the provider redirect can be observed by `QWebEngineView`.
- Use loopback callback capture as the automatic fallback when a provider or registration requires a local HTTP redirect.
- Keep Microsoft client ID and optional existing secret support, but always use PKCE for interactive login.
- Keep Ely.by client ID `notg-launcher` and omit `client_secret` unless explicitly configured. Use Ely.by authserver credential login as the default launcher flow and store only the returned access/client tokens.
- Convert provider/network failures into actionable messages and write diagnostic details to the launcher logger.

## Sources Checked

- Microsoft identity platform authorization code flow with PKCE: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
- Microsoft identity platform device authorization flow: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
- Microsoft reply URL/native client guidance: https://learn.microsoft.com/en-us/entra/identity-platform/reply-url
- OAuth 2.0 for native apps loopback and external-agent guidance: https://datatracker.ietf.org/doc/html/rfc8252
- minecraft-launcher-lib Microsoft helper implementation: `.venv/Lib/site-packages/minecraft_launcher_lib/microsoft_account.py`
- Ely.by OAuth documentation: https://docs.ely.by
- Ely.by launcher authentication documentation: https://docs.ely.by/en/minecraft-auth.html
- Ely.by skinsystem documentation confirms public texture/profile endpoints are read-only and says users cannot self-assign capes: https://docs.ely.by/en/skins-system.html
