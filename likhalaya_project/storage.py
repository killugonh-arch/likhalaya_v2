"""
likhalaya_project/storage.py

Cloudinary storage that keeps payment/delivery proof images PRIVATE.
Everything else (products, categories, avatars, QR codes) stays public.

Private folders are uploaded as Cloudinary type "authenticated", so their
direct Cloudinary URL stops working. Django serves them through
/private-media/<path> after a login + ownership check (see private_media.py).
"""
import cloudinary
import cloudinary.uploader
import cloudinary.utils
import os

from cloudinary_storage.storage import MediaCloudinaryStorage
from django.urls import reverse

PRIVATE_FOLDERS = ('payment_proofs', 'pickup_proofs', 'delivery_proofs')


def is_private(name):
    n = (name or '').replace('\\', '/').lstrip('/')
    if n.startswith('media/'):
        n = n[len('media/'):]
    return n.split('/', 1)[0] in PRIVATE_FOLDERS


class SmartCloudinaryStorage(MediaCloudinaryStorage):

    def _upload(self, name, content):
        options = {
            'use_filename': True,
            'resource_type': self._get_resource_type(name),
            'tags': self.TAG,
        }
        folder = os.path.dirname(name)
        if folder:
            options['folder'] = folder
        if is_private(name):
            options['type'] = 'authenticated'
        return cloudinary.uploader.upload(content, **options)

    def delete(self, name):
        kwargs = {'invalidate': True, 'resource_type': self._get_resource_type(name)}
        if is_private(name):
            kwargs['type'] = 'authenticated'
        response = cloudinary.uploader.destroy(name, **kwargs)
        return response['result'] == 'ok'

    def signed_url(self, name):
        """Real (signed) Cloudinary URL. Server-side use only, never in HTML."""
        return cloudinary.utils.cloudinary_url(
            self._prepend_prefix(name),
            type='authenticated',
            resource_type=self._get_resource_type(name),
            sign_url=True,
            secure=True,
        )[0]

    def _get_url(self, name):
        # used internally by _open / exists / size
        if is_private(name):
            return self.signed_url(name)
        return super()._get_url(name)

    def url(self, name):
        # what templates get from {{ field.url }}
        if is_private(name):
            return reverse('private_media', kwargs={'path': name})
        return super().url(name)