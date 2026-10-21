"""Copy only operator-installed OCR libraries and the English model into isolation."""

import hashlib
import shutil
from pathlib import Path


def files(root):
    if root is None:
        return []
    root = Path(root).resolve()
    model = root / "tessdata/eng.traineddata"
    if not model.is_file():
        raise ValueError("Configured OCR installation lacks English traineddata")
    return [(model, "tessdata/eng.traineddata"), *((p, p.name) for p in sorted(root.glob("*.dll")))]


def version(root):
    digest = hashlib.sha256()
    for path, name in files(root):
        digest.update(name.encode())
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1_000_000), b""):
                digest.update(block)
    return digest.digest()


def copy(root, runtime):
    for path, name in files(root):
        target = runtime / "ocr" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
