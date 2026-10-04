# NOTG Launcher User Guide

NOTG Launcher keeps every Minecraft setup in its own **instance**. Your mods, worlds, screenshots, settings, logs, and playtime stay separate for each one.

This guide keeps the important things first. The italic notes below each point explain the extra details when you need them.

## 1. Use the Home Screen

### Main Things You Can Do

- **Create a new instance** with **Add Instance**.
  *Choose a Minecraft version, mod loader, name, and icon, then install it.*

- **Launch an instance** with **Launch** or by double-clicking its card.
  *Use **Kill** if you need to stop a running game.*

- **Edit an instance** to manage its version, mods, screenshots, memory, Java, and more.
  *Select the instance first, then choose **Edit**.*

- **Open, copy, or delete an instance** from its card.
  *Use **Folder** to open its files. **Copy** makes a full duplicate. **Delete** permanently removes the instance after confirmation, so stop a running game first.*

- **Manage launcher-wide settings** from the top bar.
  *Use **Folders** for all launcher instances, **Settings** for launcher options, and the question-mark button for online help.*

- **Switch accounts** from the account button in the top-right corner.
  *Choose an existing account or open **Manage Accounts** to add or remove one.*

- **Check your playtime** at the bottom of the launcher.
  *It shows the current session, the selected instance total, and your total time across all instances.*

## 2. Create, Import, and Install

### Create a New Instance

- Open **Add Instance** and stay on **Create**.
  *Enter a name if you want one. If you leave it empty, NOTG uses the selected version and loader for the name.*

- Choose a Minecraft version and mod loader.
  *Use **None** for vanilla Minecraft, or choose NeoForge, Forge, Fabric, or Quilt. The launcher only shows compatible loader versions.*

- Pick an icon if you want your instance to look different.
  *Select the large icon to choose a built-in icon or add your own PNG image.*

- Select **Install** and wait for it to finish.
  *The new instance appears on the Home Screen after installation is complete.*

### Use Advanced Options Only When Needed

- **Copy files from another instance** when creating a new one.
  *Move only the worlds, mods, settings, or other files you want into **Copy To**. This is not the same as making a full copy from the Home Screen.*

- **Change Minecraft memory** for larger modpacks.
  *NOTG recommends a safe amount by default. Keep **Optimize Minecraft** enabled unless you know which JVM settings you need. Do not give Minecraft almost all of your system memory.*

### Import an Existing Setup

- Import a modpack archive or an existing `.minecraft` folder from **Add Instance** → **Import**.
  *Use one source at a time. NOTG supports `.mrpack` and `.zip` archives, and you can select which files to bring over when importing a folder.*

- Choose the Minecraft version yourself if NOTG cannot detect it.
  *Select **Choose Version**, then choose the Minecraft version and loader before installing.*

- Import only a real Minecraft folder.
  *The folder needs `saves`, `mods`, and `options.txt`, either directly inside it or inside its `.minecraft` folder.*

### Install Modrinth Modpacks

- Browse and install Modrinth modpacks directly from **Add Instance** → **Modpacks**.
  *Search for a pack, open it, choose a version, and select **Install**.*

- Use filters to find a compatible modpack version.
  *You can filter by Minecraft version, loader, release type, and newest or oldest versions. The modpack decides its own Minecraft version and loader.*

- Let the installation finish before launching the pack.
  *You can review or reinstall its version stack later in **Edit** → **Versions**.*

## 3. Manage an Instance

### Change Versions Safely

- Change Minecraft or the mod loader from **Edit** → **Versions**.
  *Choose the version, select a compatible loader if needed, then use **Install** and confirm the reinstall.*

- Check your mods after changing versions.
  *Reinstalling keeps your normal instance data, but installed mods may no longer match the new game version or loader.*

### Manage Mods and Resource Packs

- Enable, disable, remove, search, or open the folder for installed mods from **Edit** → **Mods**.
  *Disabling moves mods out of the active mods folder. Removing mods permanently deletes the selected files after confirmation.*

- Install Mods or Resource Packs from Modrinth without leaving the launcher.
  *The browser already uses the instance Minecraft version and loader. It also installs compatible required dependencies when available.*

- Keep resource packs separate from mods.
  *Resource packs install into the instance resource-pack folder, so they do not appear as mod rows.*

### Check Logs and Screenshots

- Use **Minecraft Log** to inspect the latest game log, especially after a crash.
  *You can search, copy, clear the current view, or jump back to the newest line. Clearing the view does not delete the log file.*

- Manage screenshots from **Edit** → **Screenshots**.
  *Copy the first selected image, rename one image, delete selected images, or open the screenshots folder.*

### Set Discord Rich Presence

- Turn on **Enable Rich Presence for this instance** if you want Discord to show that you are playing.
  *You can set custom State and Details text, or leave them empty to use the default game activity. **Adaptive Details** lets the details follow the current game activity.*

### Advanced Instance Settings

- Copy selected files into an existing instance from **Advanced**.
  *This replaces the selected current files after confirmation, so use it carefully. It is different from creating a full instance copy.*

- Keep Java on **Automatic** unless you need a specific installed Java version.
  *Use **Refresh** after installing Java and **Save Java** to keep a manual choice. NOTG will not save a Java runtime that is too old for the selected Minecraft version.*

- Add JVM arguments only if you know what they do.
  *Use **Custom JVM Launch Command** for extra arguments. Leaving the normal optimization settings enabled is the best choice for most players.*

## 4. Customize the Launcher

### General Settings

- Choose whether the launcher closes after Minecraft starts.
  *This is available in **Settings** → **General**.*

- Turn the loading screen on or off.
  *Use **Always show loading screen** if you want to see it every time the launcher opens.*

- Enable the **F3 + M** crash shortcut only if you need it.
  *It can stop running instances, so do not enable it if you might press it while playing by accident.*

### Make It Look Like Yours

- Change the launcher background, theme mode, and accent colour in **Settings** → **Appearance**.
  *You can add your own image or video background. Built-in backgrounds cannot be removed.*

- Manage your custom backgrounds from the background picker.
  *Use **Add Background**, **Remove Background**, or **Open Folder**. The displayed **Adapt to Music** option is currently unavailable.*

### Keep NOTG Updated

- Check for launcher updates in **Settings** → **Updates**.
  *Choose **Check for Updates**, read the patch notes, then select **Install Update** when one is available. Let NOTG restart itself to finish the update.*

## 5. Use the Music Player

### Play Music

- Open **Music Manager** from the three-dot button in the top music player.
  *The compact player also gives you volume and mute controls.*

- Select a playlist and press **Play**.
  *Use the player controls for previous, next, play/pause, seeking, volume, mute, shuffle, and loop.*

### Build Your Playlists

- Create a playlist with the plus button in the sidebar.
  *Use the three-dot edit button to rename it, change its icon, add tracks, or delete it. At least one playlist must stay available.*

- Add local music files or supported online music links.
  *Use **Browse** for local audio, or paste a supported song or playlist link and choose **Add**. You can drag tracks to change their order.*

- Keep music playing when the launcher closes if a Minecraft game is running.
  *Turn on the window/play icon in the sidebar. NOTG hides instead of fully closing while a game session is active, so your music can continue.*

## 6. Manage Accounts, Skins, and Capes

### Use an Account

- Add or switch accounts from the account button in the top-right corner.
  *Open **Manage Accounts**, select an account, then choose **Use Account** before launching Minecraft.*

- Add an offline account with a simple username.
  *Offline usernames must use 3–16 letters, numbers, or underscores.*

- Log in with an Ely.by account if you use one.
  *Choose **Ely.by Account**, enter your details, and enter a two-factor code if Ely.by asks for one.*

- Remove accounts you no longer use.
  *Use **Remove Account** in account management. Microsoft account login is currently marked as coming soon in the launcher.*

### Use Skins and Capes

- Upload a PNG skin or cape for an offline account.
  *Open **Skin & Cape**. You can upload or drag in a skin PNG, upload a cape PNG, remove either one, and choose the Classic or Slim skin model. Offline skins are stored locally by NOTG.*

- Refresh or download your Ely.by skin.
  *Use **Open Ely.by** to change your online appearance on the Ely.by website. Ely.by capes can be refreshed in NOTG, but must be uploaded on Ely.by.*

- Remember that offline skins are not official Minecraft profile skins.
  *Other players usually will not see them unless their client uses a compatible offline-skin setup.*

## 7. Before You Launch

### Quick Checks

- Make sure the correct account is selected.
  *Check the account button in the top-right corner before pressing **Launch**.*

- Make sure your Minecraft version, loader, and mods match.
  *A mod made for a different version or loader can stop the game from starting.*

- Leave memory and Java on the recommended settings unless your setup needs more.
  *Automatic Java and NOTG's memory recommendation are the safest choices for most instances.*

- Wait for downloads and installs to finish.
  *Do not launch a game or start another major change while an instance, modpack, mod, or launcher update is still installing.*
