# NOTG Launcher User Guide

This guide uses the labels shown in NOTG Launcher. Each Minecraft setup is an **instance**: its game files, mods, screenshots, logs, settings, and playtime are kept separate from other instances.

## 1. Use the home screen

The top bar is the starting point for launcher-wide tasks:

- **Add Instance** opens **Create New Instance**.
- **Folders** opens the folder that contains all launcher-managed instances.
- **Settings** opens launcher settings.
- The question-mark button opens the online NOTG Launcher help page.
- Select the account chip at the top right to switch to an existing account or choose **Manage Accounts**.

To work with an existing instance, select its card. The left panel shows the selected instance's icon, version, status, and these actions:

- **Launch** starts the selected instance. You can also double-click its card.
- **Kill** stops the selected running instance.
- **Edit** opens the detailed instance editor.
- **Folder** opens that instance's root folder.
- **Copy** creates a full duplicate with an automatically generated `Copy` name.
- **Delete** permanently removes the instance and all of its files after confirmation. Stop a running instance before deleting it.

Right-clicking an instance card also provides **Edit**, **Folder**, **Copy**, and **Delete**. The bar at the bottom shows the selected instance's current-session and instance-total playtime, plus total playtime across all instances.

## 2. Create a new instance

1. Select **Add Instance**.
2. In the left navigation, keep **Create** selected, then open the **General** tab.
3. Optionally enter a name in **Enter a name or use the selected version**. If left blank, NOTG uses the selected Minecraft version and loader to create a name.
4. To change the card image, select the large icon at the top. In **Pick Icon**, select an icon and choose **OK**. Use **Add Icon** to add a PNG, or **Open Folder** to access the custom-icon folder. Default icons cannot be removed.
5. Under **Version**, select a Minecraft version. Use **Search versions** or the **Releases**, **Snapshots**, **Betas**, **Alphas**, and **Experiments** filters when needed. **Refresh** reloads the catalogue.
6. Under **Mod Loader**, select **None**, **NeoForge**, **Forge**, **Fabric**, or **Quilt**. When you select a loader, choose a compatible loader version from the list. Leave **None** selected for a vanilla instance.
7. Select **Install**. Keep the installation-progress window open until it finishes. The new instance then appears on the home screen.

### Optional creation settings

Open the **Advanced** tab before selecting **Install** when you need either option below.

- **Copy From Instance** lets you select another instance, choose its available user-data entries, and move entries to **Copy To**. The `>` and `<` buttons move selected entries; `>>` moves all entries and `<<` clears the selection. This copies only the chosen data into the newly created instance, not a full clone.
- **Memory** controls Minecraft's allocation in 256 MB steps. **Optimize Minecraft** is enabled by default. Use **Revert** to return to NOTG's recommended allocation, and **Confirm** to keep the displayed value. **Go Beyond** raises the slider limit; only enable it if enough memory remains for Windows and other programs.

## 3. Import an existing setup or install a modpack

### Import an archive or `.minecraft` folder

1. Select **Add Instance**, then choose **Import** in the left navigation.
2. Choose one source only:
   - For an exported pack, use the **Browse** button beside **Select a modpack archive (.mrpack or .zip)**.
   - For an existing Minecraft setup, use **Browse** beside **Select a .minecraft folder to import**.
3. When importing a `.minecraft` folder, select the files and folders to bring across in the selection window, then choose **Import**.
4. If NOTG cannot identify the imported Minecraft version, select **Choose Version**, select the Minecraft version and, if applicable, mod loader and loader version.
5. Optionally set the instance name, icon, or Advanced memory settings, then select **Install**.

For a folder import, choose either the actual `.minecraft` folder or a folder containing it. The source must contain `saves`, `mods`, and `options.txt`; this prevents accidental imports of unrelated folders.

### Browse Modrinth modpacks

1. Select **Add Instance** and choose **Modpacks**. The **Modrinth Modpacks** browser opens automatically; **Open Modpacks** opens it again if necessary.
2. Enter a search in **Search modpacks…** and select **Search**, or browse the popular packs shown initially.
3. Select a modpack to view its description, gallery, and **Versions**.
4. Use **All MC**, **All Loaders**, **Newest** / **Oldest**, and the **Release**, **Beta**, and **Alpha** filters to find a compatible pack version.
5. Select **Install** on the desired version row. The browser downloads the pack, then NOTG creates the instance and shows installation progress.

Wait for the installation to complete before launching the pack. The pack's own Minecraft version and loader are used; review them in **Edit** > **Versions** if you later need to reinstall the version stack.

## 4. Edit an instance

Select an instance, then choose **Edit**. The name field at the top saves when you finish editing it; use the icon to open **Pick Icon**. The editor also has **Launch**, **Force Stop**, and **OK** at the bottom.

### Minecraft Log

Use **Minecraft Log** to read the instance's latest log while it is running or after a crash.

- **Copy** copies the displayed log text.
- **Clear** clears the current view; it does not delete the log file.
- Enter text in **Search log text**, then choose **Find** to locate it.
- **Bottom** returns to the latest displayed log line.

### Versions

Open **Versions** to change the Minecraft version or mod loader after creation.

1. Select a Minecraft version, then select **None**, **NeoForge**, **Forge**, **Fabric**, or **Quilt** as appropriate.
2. If a loader is selected, choose one compatible loader version.
3. Select **Install** when the editor reports **Reinstall to apply the selected version stack.**
4. Confirm **Reinstall Version**.

Reinstalling replaces the current version files while retaining the instance's copyable user data. It can still make installed mods incompatible, so check the **Mods** page before launching.

### Mods and resource packs

The **Mods** page lists installed and disabled mod archives. Select one or more rows, then use:

- **Enable** or **Disable** to move selected mods between the active and disabled locations.
- **Remove** to permanently delete selected mod files after confirmation.
- **View Folder** to open the active mods folder.
- **View Configs** to open the instance configuration folder.
- **Search mods** to filter by name, version, or provider.

For online content, select **Install Mods**. The separate **Mod Browser** is already matched to the instance's Minecraft version and loader.

1. Choose **Mods** or **Resource Packs**.
2. Search, choose a category, and choose **Relevance**, **Downloads**, or **Updated** sorting.
3. Select a result to inspect its compatible versions, loader support, description, and required dependencies.
4. Select **Install** in the details pane. NOTG resolves compatible required Modrinth dependencies during installation.

Close the browser, then return to **Mods** to verify a new mod. Resource packs are installed in the instance's resource-pack location, not shown as mod rows.

### Screenshots

The **Screenshots** page displays images from the instance's screenshots folder. Select one or more thumbnails and use:

- **Copy Image** to copy the first selected screenshot to the clipboard.
- **Rename** to rename exactly one selected screenshot.
- **Delete** to permanently delete selected screenshots after confirmation.
- **View Folder** to open the screenshots folder.

### Rich Presence

Under **Rich Presence**, enable **Enable Rich Presence for this instance** to let Discord show the instance while Minecraft is running.

- **State** overrides the default state text. Leave it empty to use NOTG's default.
- **Details** sets the activity detail. Leave it empty to allow game activity to provide the detail.
- **Adaptive Details** controls whether the detail follows current game activity.

Changes are saved as you toggle the option or finish editing a text field.

### Advanced: copy, memory, Java, and JVM options

**Copy From Instance** copies selected user data from another instance into the current one. Choose the source, move only the required entries to **Copy To**, select **Copy**, and confirm **Replace Current Files**. This overwrites the chosen entries in the current instance; it is not the same as the home-screen **Copy** action.

In **Memory**, use the slider, **Go Beyond**, **Revert**, and **Confirm** as described in the creation workflow. Leave **Optimize Minecraft** enabled unless you have a specific reason to use your own JVM tuning.

Under **Java & JVM**:

- Enter extra arguments only when you understand the JVM option being added; use **Custom JVM Launch Command** for these arguments.
- Leave **Java Version** on **Automatic** to select the newest compatible installed Java runtime.
- Select **Refresh** after installing or changing Java runtimes.
- Select **Save Java** to store the chosen runtime and JVM settings for this instance.

NOTG prevents saving a detected runtime that is too old for the selected Minecraft version. If Java is missing or incompatible, install a compatible Java version, then select **Refresh** or return to **Automatic**.

## 5. Customize the launcher

Select **Settings** in the top bar. Changes made in the toggle controls are saved immediately; select **OK** when finished.

### General

- **Close the launcher after game launch** closes the launcher UI after a successful launch.
- **Always show loading screen** controls whether the startup loading screen is always shown.
- **Enable F3 + M instance crash shortcut** enables the global F3+M shortcut that stops running instances. Turn it on only if you will not trigger it accidentally while playing.

### Appearance

Select **Change Background** to open **Pick Background**. Choose a built-in or custom image/video background, then select **OK**.

- **Add Background** imports a supported image or video file.
- **Remove Background** removes the selected custom background. Built-in backgrounds cannot be removed.
- **Open Folder** opens the custom-background folder.

Use the **Light mode** switch for the launcher color mode. Drag or select the theme color wheel to choose the accent color. **Adapt to Music** is currently displayed but disabled, so it is not an available customization setting.

### Updates

Open **Updates**, select **Check for Updates**, and review the release notes. If a version is offered, select **Install Update**. NOTG downloads the update and restarts the application to apply it; do not close it while the download is in progress.

## 6. Use the music player

The compact player in the top bar provides volume, mute, and a three-dot button with the tooltip **Open music manager**. Select that button to open **Music Manager**.

### Play a playlist

1. Select a playlist in the left sidebar.
2. Select **Play** to start the playlist.
3. Use the Shuffle and Loop icon buttons to toggle those modes.
4. Use the bottom playback controls for previous, play/pause, next, seeking, volume, and mute.

### Create and edit playlists

1. Select the plus icon in the Music Manager sidebar to create a playlist.
2. Select the three-dot **Edit playlist** icon for the selected playlist.
3. In **Playlist Editor**, rename the playlist, select its icon, then add music:
   - Paste a supported music or playlist URL and select **Add**. The field notes that YouTube URLs work for most supported online additions.
   - Select **Browse** to add one or more local audio files.
4. Drag tracks using their drag handles to reorder them. Use each track's preview and remove buttons as needed.
5. Select **Done** to close the editor. **Delete Playlist** is available only when at least one other playlist remains.

The sidebar's window/play icon controls **Keep music playing when launcher closes**. When music is playing and a Minecraft session is active, enabling it lets NOTG hide instead of exit so playback can continue. Without an active game session, closing the launcher stops playback.

## 7. Manage accounts, skins, and capes

### Select or add an account

Select the account chip in the top right and choose an account to make it active, or select **Manage Accounts**.

In **Manage Accounts**:

1. Select **Add Account**.
2. For an offline account, enter a username using 3–16 letters, numbers, or underscores, then select **Add**.
3. For an Ely.by account, select **Ely.by Account**, enter the email/username and password in **Ely.by Login**, then select **Log In**. If prompted, enter the two-factor code.
4. Select an account in the account list and choose **Use Account** before launching Minecraft.

The current **Microsoft Account** card is marked **Coming soon** in the launcher interface and does not open a sign-in flow. **Remove Account** removes the selected account from NOTG after confirmation.

### Skins

Select an account, open the **Skin & Cape** tab, and select **Manage Skin**.

- Offline accounts can add a PNG skin with **Upload** or by dragging a PNG into **Manage Skin**. Use **Remove** to clear the locally stored skin.
- Ely.by accounts can use **Refresh** to retrieve the skin configured on Ely.by and **Download** to save the current skin image. Use **Open Ely.by** to manage appearance on the provider's website.
- **Download** saves the currently available skin image.

Back in **Skin & Cape**, select **Classic** or **Slim** to choose the skin model, and use **Auto rotate** to control the preview animation.

An offline skin is local launcher data, not an official Minecraft profile change. Other players will not normally see it unless their own compatible client-side skin setup can resolve it.

### Capes

The **Cape** panel shows the account's current cape status. For offline accounts, use **Upload Cape** to select a PNG and **Remove Cape** to clear the local cape. Online accounts can use **Refresh Cape** to refresh the provider profile; NOTG does not provide a launcher-side Ely.by cape upload control.

## 8. Practical checks before launching

- Select the intended account in the top-right account menu before pressing **Launch**.
- Use a mod loader only when the Minecraft version and every installed mod support it.
- Keep memory near NOTG's recommended value unless a large modpack genuinely needs more; allocating nearly all system memory can make the computer and Minecraft less stable.
- Prefer **Automatic** Java unless you know a selected Java runtime is compatible. A launch error will identify when the required Java version is unavailable.
- Wait for any instance, modpack, mod, or update progress window to complete before starting another major change.
