import sys
from pathlib import Path
from urllib.request import urlopen


def run_editor(path: Path, url: str) -> None:
    # pylint: disable=invalid-name
    with urlopen(url, data=path.read_bytes(), timeout=10) as r:
        length = int(r.headers.get("content-length"))
        data = r.read(length)
        if r.status != 200:
            raise Exception(data.decode())
    path.write_bytes(data)


if __name__ == "__main__":
    run_editor(url=sys.argv[1], path=Path(sys.argv[2]).resolve())
