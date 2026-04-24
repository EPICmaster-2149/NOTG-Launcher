# Discord Rich Presence Setup

## Overview

NOTG Launcher now uses a single launcher-controlled Discord Rich Presence integration.

- Users can no longer enter their own Discord Application ID in the launcher UI.
- Rich Presence only appears while a Minecraft instance is actively running.
- Each instance can enable or disable Rich Presence and optionally override the displayed `State` and `Details`.

## Developer Setup

Configure the launcher-owned Discord application in [app/core/discord_presence.py](app/core/discord_presence.py):

```python
APPLICATION_ID = "YOUR_APP_ID_HERE"
LARGE_IMAGE_KEY = "YOUR_LARGE_IMAGE_KEY_HERE"
SMALL_IMAGE_KEY = "YOUR_SMALL_IMAGE_KEY_HERE"
```

## Asset Notes

- Create the application in the Discord Developer Portal.
- Upload Rich Presence art assets for the large and small image keys.
- Discord stores uploaded asset keys in lowercase, so make sure the configured keys match.
- Discord recommends high-resolution art assets, typically 1024x1024.

## Instance-Level Behavior

Inside `Edit Instance -> Rich Presence`:

- `Enable Rich Presence for this instance` is enabled by default.
- `State` falls back to `Playing Minecraft` when left empty.
- `Details` falls back to `Version <minecraft version> | <loader name>` when left empty.

## Runtime Behavior

- Rich Presence is created and owned by the background session monitor.
- A single RPC connection is used for the active session.
- Presence is cleared automatically when Minecraft exits.
- If Discord is not running or the launcher application ID has not been configured yet, the launcher fails silently and continues normally.
