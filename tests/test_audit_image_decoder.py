import base64
import io

from PIL import Image

from scripts.audit_image_decoder import decode_returned_images


def test_actual_pixels_decode_but_success_flags_and_corrupt_pixels_do_not():
    output = io.BytesIO()
    Image.new("RGB", (4, 3), "blue").save(output, format="PNG")
    assert decode_returned_images(
        {"content": [{"type": "image", "data": base64.b64encode(output.getvalue()).decode()}]}
    )
    assert not decode_returned_images({"data": {"rendered": True}})
    assert not decode_returned_images({"content": [{"type": "image", "data": "broken"}]})
    assert not decode_returned_images(
        {"content": [{"type": "image", "data": base64.b64encode(output.getvalue()[:25]).decode()}]}
    )
