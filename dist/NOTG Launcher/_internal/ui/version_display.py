from __future__ import annotations


def format_launcher_version_label(version: str, loader_name: str | None) -> str:
    version_text = str(version).replace("Minecraft ", "", 1).strip()
    loader_text = str(loader_name or "Vanilla").strip() or "Vanilla"
    if not version_text:
        return loader_text
    if loader_text.lower() == "vanilla":
        return version_text
    return f"{version_text} • {loader_text}"
