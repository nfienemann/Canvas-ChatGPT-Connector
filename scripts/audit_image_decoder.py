"""Decode returned MCP image blocks in memory; never fetch URLs or save pixels."""

import base64
import io
import json
import sys
import warnings

from PIL import Image


def decode_returned_images(result):
    images = [block for block in result.get("content", []) if block.get("type") == "image"]
    if not images:
        return False
    for block in images:
        data = block.get("data", "")
        if not isinstance(data, str) or len(data) > 24_000_000:
            return False
        try:
            raw = base64.b64decode(data, validate=True)
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as picture:
                    picture.verify()
                with Image.open(io.BytesIO(raw)) as picture:
                    picture.load()
                    if picture.width < 1 or picture.height < 1:
                        return False
        except (ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            return False
    return True


if __name__ == "__main__":
    try:
        value = sys.stdin.buffer.read(25_000_001)
        decoded = len(value) <= 25_000_000 and decode_returned_images(json.loads(value))
    except (ValueError, TypeError, AttributeError):
        decoded = False
    print(json.dumps({"decoded": decoded}))
