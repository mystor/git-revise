import sys
from pathlib import Path
from urllib.request import urlopen


def run_editor(path: Path) -> None:
    # pylint: disable=invalid-name
    with urlopen("http://127.0.0.1:8190/", data=path.read_bytes(), timeout=5) as r:
        length = int(r.headers.get("content-length"))
        data = r.read(length)
        if r.status != 200:
            raise Exception(data.decode())
    path.write_bytes(data)


if __name__ == "__main__":
    run_editor(path=Path(sys.argv[1]).resolve())
