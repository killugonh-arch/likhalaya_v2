"""One shared image-upload check for the whole site.

Same approach as orders/validators.py (payment proofs): the upload is CHECKED
and, if it passes, SANITIZED in place:
  1. size bounds
  2. extension is jpg / jpeg / png / webp
  3. content really decodes as an image (stops renamed .php/.html/.exe)
  4. the real format matches the extension (stops a GIF/BMP renamed to .jpg)
  5. sane dimensions (stops decompression bombs)
  6. re-encoded from pixels: EXIF/GPS, comments and any payload appended
     after the image data are dropped, and the filename becomes random.

Use it three ways:
  - sanitize_image(upload, ...)  -> error string or None   (views)
  - SafeImageFormMixin           -> every ImageField in a form gets checked
  - install_image_guard()        -> last-line backstop: any browser/API upload
                                    that reaches a model's ImageField is checked
                                    before it is saved (even Django admin).
"""
import io
import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import models
from django.db.models.signals import pre_save
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {
    'JPEG': ('.jpg', '.jpeg'),
    'PNG': ('.png',),
    'WEBP': ('.webp',),
}
DEFAULT_MAX_BYTES = 5 * 1024 * 1024   # 5 MB
MAX_PIXELS = 25_000_000
MAX_SIDE = 8000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

INVALID_MSG = "That file doesn't look like a valid image. Please upload a JPG, PNG or WEBP photo."


def sanitize_image(upload, max_bytes=DEFAULT_MAX_BYTES, min_bytes=0, quality=92):
    """Returns an error message, or None when `upload` is fine (and has then
    been sanitized in place)."""
    if upload is None:
        return None
    if getattr(upload, '_lk_clean', False):
        return None  # already checked earlier in this request

    if upload.size < min_bytes:
        return f'That image is too small (must be at least {max(min_bytes // 1024, 1)} KB).'
    if upload.size > max_bytes:
        mb = max_bytes / (1024 * 1024)
        limit = f'{mb:g} MB' if mb >= 1 else f'{max_bytes // 1024} KB'
        return f'That image is too large (must be {limit} or smaller).'

    name = (upload.name or '').lower()
    if '.' not in name:
        return INVALID_MSG
    ext = '.' + name.rsplit('.', 1)[-1]
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        return 'Only JPG, PNG or WEBP images are allowed.'

    try:
        upload.seek(0)
        probe = Image.open(upload)
        probe.verify()                      # raises if not a real image
        fmt = probe.format
        upload.seek(0)
        img = Image.open(upload)            # verify() invalidates; reopen
        width, height = img.size
        if fmt not in ALLOWED_FORMATS or ext not in ALLOWED_FORMATS[fmt]:
            return INVALID_MSG
        if width * height > MAX_PIXELS or max(width, height) > MAX_SIDE:
            return 'That image has unrealistic dimensions.'

        img = ImageOps.exif_transpose(img)  # keep rotation, then drop metadata
        buf = io.BytesIO()
        if fmt == 'JPEG':
            img.convert('RGB').save(buf, 'JPEG', quality=quality, optimize=True)
            new_ext, ctype = '.jpg', 'image/jpeg'
        elif fmt == 'PNG':
            img.save(buf, 'PNG', optimize=True)
            new_ext, ctype = '.png', 'image/png'
        else:
            img.save(buf, 'WEBP', quality=quality)
            new_ext, ctype = '.webp', 'image/webp'
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        return INVALID_MSG
    finally:
        upload.seek(0)

    data = buf.getvalue()
    if hasattr(upload, 'temporary_file_path'):
        # Big uploads live in a temp file and Django may MOVE that file as-is
        # when saving, so overwrite its bytes instead of just swapping the
        # file object (otherwise the unsanitized original would be stored).
        upload.file.seek(0)
        upload.file.truncate()
        upload.file.write(data)
        upload.file.flush()
        upload.file.seek(0)
    else:
        upload.file = io.BytesIO(data)
    upload.size = len(data)
    upload.name = f'{uuid.uuid4().hex}{new_ext}'
    upload.content_type = ctype
    upload._lk_clean = True
    return None


class SafeImageFormMixin:
    """Put FIRST in a form's bases (class MyForm(SafeImageFormMixin, forms.ModelForm)).
    Every ImageField in the form is checked + sanitized; a bad file becomes a
    normal field error."""
    image_max_bytes = DEFAULT_MAX_BYTES

    def clean(self):
        cleaned = super().clean()
        cleaned = cleaned if cleaned is not None else self.cleaned_data
        for name, field in self.fields.items():
            if not isinstance(field, forms.ImageField):
                continue
            value = cleaned.get(name)
            if isinstance(value, UploadedFile):   # a NEW upload, not a saved file
                error = sanitize_image(value, max_bytes=self.image_max_bytes)
                if error:
                    self.add_error(name, error)
        return cleaned


def _guard_images(sender, instance, **kwargs):
    """pre_save backstop for browser/API uploads that skipped a form check."""
    for field in sender._meta.concrete_fields:
        if not isinstance(field, models.ImageField):
            continue
        ff = getattr(instance, field.attname, None)
        if not ff or getattr(ff, '_committed', True):
            continue
        upload = getattr(ff, 'file', None)
        if not isinstance(upload, UploadedFile):
            continue  # server-generated file (e.g. the QR generator): trusted
        error = sanitize_image(upload)
        if error:
            raise ValidationError({field.name: error})
        ff.name = upload.name


def install_image_guard():
    pre_save.connect(_guard_images, dispatch_uid='likhalaya_image_guard')