import sys
from pathlib import Path
from urllib.request import urlopen


def run_editor(path: Path, url: str) -> None:
    with urlopen(url, data=path.read_bytes(), timeout=10) as request:
        length = int(request.headers.get("content-length"))
        data = request.read(length)
        if request.status != 200:
            raise RuntimeError(data.decode())
    path.write_bytes(data)


if __name__ == "__main__":
    run_editor(url=sys.argv[1], path=Path(sys.argv[2]).resolve())
