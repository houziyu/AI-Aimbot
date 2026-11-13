"""Fetch the documented public Apex evaluation media into ignored local artifacts."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urljoin
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


def fetch(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def verify(path, expected):
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Source changed: {path.name}; SHA256 {actual}, expected {expected}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", action="store_true", help="Also fetch the approximately 69 MB public video")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/apex-validation")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "tests/fixtures/apex-sources.json").read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    for item in manifest["images"]:
        path = args.output / item["file"]
        if not path.exists():
            path.write_bytes(fetch(item["url"]))
        verify(path, item["sha256"])
        print(f"Verified {path.name}", flush=True)
    if args.video:
        item = manifest["video"]
        path = args.output / item["file"]
        if not path.exists():
            playlist = item["playlist"]
            content = fetch(playlist).decode("utf-8")
            init = re.search(r'#EXT-X-MAP:URI="([^"]+)"', content)
            if init is None or "#EXT-X-KEY" in content:
                raise ValueError("Unsupported public video manifest")
            parts = [init.group(1)] + [line for line in content.splitlines() if line and not line.startswith("#")]
            temporary = path.with_suffix(".partial")
            with ThreadPoolExecutor(max_workers=4) as pool, temporary.open("wb") as output:
                for blob in pool.map(fetch, [urljoin(playlist, part) for part in parts]):
                    output.write(blob)
            verify(temporary, item["sha256"])
            temporary.replace(path)
        verify(path, item["sha256"])
        print(f"Verified {path.name}", flush=True)


if __name__ == "__main__":
    main()
