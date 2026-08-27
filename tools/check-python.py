#!/usr/bin/python3
from __future__ import print_function

import os
import sys


def main():
    count = 0
    for root, directories, files in os.walk("linux"):
        directories[:] = [item for item in directories if item != "__pycache__"]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            with open(path, "rb") as stream:
                source = stream.read()
            compile(source, path, "exec", 0, True)
            count += 1
    print("Python syntax OK: {0} files".format(count))
    return 0


if __name__ == "__main__":
    sys.exit(main())

