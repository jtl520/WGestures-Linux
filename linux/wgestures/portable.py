from __future__ import unicode_literals

import copy
import json

from .config import normalize_config
from .importer import import_legacy_config


FORMAT_NAME = "crossgestures-portable"
FORMAT_VERSION = 1


def export_portable_config(config):
    """Return the stable, UTF-8 JSON representation shared with Windows."""
    normalized = normalize_config(config)
    document = copy.deepcopy(normalized["config"])
    document["portableFormat"] = FORMAT_NAME
    document["schemaVersion"] = FORMAT_VERSION
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def import_config(text):
    """Import either a portable .cgestures document or a legacy Windows .wg2."""
    try:
        document = json.loads(text)
    except (TypeError, ValueError) as error:
        raise ValueError("配置不是有效 JSON：{0}".format(error))
    if not isinstance(document, dict) or document.get("portableFormat") != FORMAT_NAME:
        return import_legacy_config(text)
    if document.get("schemaVersion") != FORMAT_VERSION:
        raise ValueError("不支持的 CrossGestures 跨平台配置版本：{0}".format(
            document.get("schemaVersion")))
    normalized = normalize_config(document)
    config = normalized["config"]
    profiles = [config["globalProfile"]] + config["profiles"]
    unbound = [{
        "id": profile["id"], "name": profile["name"],
        "path": profile.get("legacyExecutablePath", ""),
    } for profile in config["profiles"]
        if profile.get("legacyExecutablePath") and not profile.get("matchers")]
    return {
        "config": config,
        "report": {
            "imported": sum(len(profile["gestures"]) for profile in profiles),
            "unsupported": list(normalized["warnings"]),
            "unboundProfiles": unbound,
            "portable": True,
        },
    }
