"""Shared validation for uploaded payment-proof screenshots.

Used by both the web flow (orders/views.py: gcash_payment_pending,
gcash_payment) and the API flow (api/views.py: OrderViewSet.upload_payment_proof)
so a file can't be accepted by one path but rejected by the other.

validate_payment_proof() both CHECKS the upload and, if it passes, SANITIZES
it in place: the image is decoded and re-encoded from pixels only, given a
random filename, and stripped of metadata / appended bytes. Callers don't
need to change — they keep saving `proof` exactly as before.
"""
import io
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')
MIN_PROOF_SIZE = 50 * 1024    # 50 KB
MAX_PROOF_SIZE = 2048 * 1024  # 2048 KB (2 MB)

# Real formats (as detected from file CONTENT) we accept, and the extensions
# each one may legitimately carry.
ALLOWED_FORMATS = {
    'JPEG': ('.jpg', '.jpeg'),
    'PNG': ('.png',),
    'WEBP': ('.webp',),
}

# Decompression-bomb guard: a tiny file can declare a gigantic canvas and
# exhaust server RAM when decoded. Phone screenshots are ~1080x2400 (~2.6 MP);
# 25 MP leaves lots of headroom.
MAX_PIXELS = 25_000_000
MAX_SIDE = 8000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def validate_payment_proof(proof):
    """Returns an error message string if `proof` is not acceptable,
    or None if it's fine (and `proof` has then been sanitized in place).
    Checks, in order:
      1. size bounds
      2. file extension is an allowed image type
      3. the content decodes as a real image (stops renamed .exe/.php/.html)
      4. the REAL format matches the extension (stops a GIF/BMP/TIFF renamed
         to .jpg) and the dimensions are sane (stops decompression bombs)
      5. re-encode from pixels: strips EXIF/GPS, comments, and any script or
         payload appended after the image data (polyglot files), and replaces
         the user-controlled filename with a random one.
    """
    if proof.size < MIN_PROOF_SIZE:
        return f'That image is too small to be a real GCash receipt screenshot (must be at least {MIN_PROOF_SIZE // 1024} KB).'
    if proof.size > MAX_PROOF_SIZE:
        return f'That image is too large (must be under {MAX_PROOF_SIZE // 1024} KB).'

    name = (proof.name or '').lower()
    if not name.endswith(ALLOWED_EXTENSIONS):
        return 'Please upload a JPG, PNG, or WEBP image of your GCash receipt.'
    ext = '.' + name.rsplit('.', 1)[-1]

    invalid = "That file doesn't look like a valid image. Please upload a real screenshot."
    try:
        proof.seek(0)
        probe = Image.open(proof)
        probe.verify()  # raises if the content isn't actually a valid image
        fmt = probe.format
        proof.seek(0)
        img = Image.open(proof)  # verify() invalidates the object; reopen
        width, height = img.size
        if fmt not in ALLOWED_FORMATS or ext not in ALLOWED_FORMATS[fmt]:
            return invalid
        if width * height > MAX_PIXELS or max(width, height) > MAX_SIDE:
            return 'That image has unrealistic dimensions. Please upload a normal phone screenshot.'

        img = ImageOps.exif_transpose(img)  # apply rotation before metadata is dropped
        buf = io.BytesIO()
        if fmt == 'JPEG':
            img.convert('RGB').save(buf, 'JPEG', quality=90, optimize=True)
            new_ext, ctype = '.jpg', 'image/jpeg'
        elif fmt == 'PNG':
            img.save(buf, 'PNG', optimize=True)
            new_ext, ctype = '.png', 'image/png'
        else:
            img.save(buf, 'WEBP', quality=90)
            new_ext, ctype = '.webp', 'image/webp'
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return invalid
    finally:
        proof.seek(0)

    # Swap the sanitized bytes in so Django saves THIS, not the original upload.
    buf.seek(0)
    proof.file = buf
    proof.size = buf.getbuffer().nbytes
    proof.name = f'{uuid.uuid4().hex}{new_ext}'
    proof.content_type = ctype
    return None