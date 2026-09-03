from collections import OrderedDict
from io import BytesIO

from PIL import Image


def to_bmp_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("1").save(buffer, format="BMP")
    return buffer.getvalue()


def to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("1").save(buffer, format="PNG")
    return buffer.getvalue()


class ImageCache:
    def __init__(self, max_entries: int = 4) -> None:
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._max_entries = max_entries

    def get(self, name: str) -> bytes | None:
        payload = self._entries.get(name)
        if payload is not None:
            self._entries.move_to_end(name)
        return payload

    def put(self, name: str, payload: bytes) -> None:
        self._entries[name] = payload
        self._entries.move_to_end(name)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
