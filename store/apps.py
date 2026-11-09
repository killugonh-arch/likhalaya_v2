from django.apps import AppConfig


class StoreConfig(AppConfig):
    name = 'store'

    def ready(self):
        # Last-line check on every browser/API image upload (see
        # likhalaya_project/image_validation.py).
        from likhalaya_project.image_validation import install_image_guard
        install_image_guard()