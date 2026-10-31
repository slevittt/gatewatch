import sys
import time

_file = None


def setup(path: str = "") -> None:
    global _file
    _file = path or None


def log(msg: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, file=sys.stderr, flush=True)
    if _file:
        try:
            with open(_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
