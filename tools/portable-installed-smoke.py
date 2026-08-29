from __future__ import print_function

import json
import sys


sys.path.insert(0, "/usr/lib/wgestures")

from wgestures.config import create_default_config
from wgestures.portable import export_portable_config, import_config


text = export_portable_config(create_default_config())
result = import_config(text)
assert result["report"]["portable"] is True
assert result["report"]["imported"] == 3
assert not result["report"]["unsupported"]
assert result["config"] == create_default_config()
print(json.dumps({"passed": True, "gestures": result["report"]["imported"]},
                 sort_keys=True))
