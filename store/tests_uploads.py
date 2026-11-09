import io
import shutil
import tempfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, TemporaryUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from accounts.models import CustomUser
from likhalaya_project.image_validation import sanitize_image
from store.forms import ProductImageForm

TMP_MEDIA = tempfile.mkdtemp()
LOCAL_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def make_image(fmt='PNG', size=(200, 200)):
    buf = io.BytesIO()
    Image.effect_noise(size, 80).convert('RGB').save(buf, fmt)
    return buf.getvalue()


def upload(name, data, ctype='image/png'):
    return SimpleUploadedFile(name, data, content_type=ctype)


class SanitizeImageTests(SimpleTestCase):
    def test_real_png_passes_and_is_renamed(self):
        f = upload('my photo.png', make_image('PNG'))
        self.assertIsNone(sanitize_image(f))
        self.assertRegex(f.name, r'^[0-9a-f]{32}\.png$')

    def test_text_file_renamed_to_jpg_rejected(self):
        f = upload('evil.jpg', b'<?php system($_GET["c"]); ?>', 'image/jpeg')
        self.assertIsNotNone(sanitize_image(f))

    def test_html_renamed_to_png_rejected(self):
        f = upload('x.png', b'<html><script>alert(1)</script></html>')
        self.assertIsNotNone(sanitize_image(f))

    def test_gif_renamed_to_jpg_rejected(self):
        f = upload('x.jpg', make_image('GIF'), 'image/jpeg')
        self.assertIsNotNone(sanitize_image(f))

    def test_disallowed_extension_rejected(self):
        f = upload('x.svg', b'<svg onload=alert(1)/>', 'image/svg+xml')
        self.assertIsNotNone(sanitize_image(f))

    def test_payload_appended_after_image_is_stripped(self):
        f = upload('x.png', make_image('PNG') + b'<?php evil(); ?>')
        self.assertIsNone(sanitize_image(f))
        f.seek(0)
        self.assertNotIn(b'<?php', f.read())

    def test_too_big_rejected(self):
        f = upload('x.png', make_image('PNG'))
        self.assertIn('too large', sanitize_image(f, max_bytes=100))

    def test_temp_file_upload_is_rewritten_in_place(self):
        data = make_image('PNG') + b'<?php evil(); ?>'
        f = TemporaryUploadedFile('x.png', 'image/png', len(data), 'utf-8')
        f.write(data)
        f.seek(0)
        self.assertIsNone(sanitize_image(f))
        with open(f.temporary_file_path(), 'rb') as fh:
            self.assertNotIn(b'<?php', fh.read())


@override_settings(MEDIA_ROOT=TMP_MEDIA, STORAGES=LOCAL_STORAGES)
class FormAndGuardTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    def test_form_rejects_fake_image(self):
        form = ProductImageForm(
            data={'caption': '', 'order': 0, 'size': ''},
            files={'image': upload('evil.png', b'not an image at all')},
        )
        self.assertFalse(form.is_valid())
        self.assertIn('image', form.errors)

    def test_guard_blocks_fake_upload_even_without_form(self):
        user = CustomUser(username='g@example.com', email='g@example.com')
        user.avatar = upload('evil.png', b'<?php evil(); ?>')
        with self.assertRaises(ValidationError):
            user.save()

    def test_guard_cleans_good_upload(self):
        user = CustomUser(username='h@example.com', email='h@example.com')
        user.avatar = upload('me.png', make_image('PNG'))
        user.save()
        self.assertRegex(user.avatar.name, r'avatars/[0-9a-f]{32}\.png$')