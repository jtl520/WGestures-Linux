#!/usr/bin/python3
from __future__ import print_function

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wgestures.cli import main


if __name__ == "__main__":
    sys.exit(main())

