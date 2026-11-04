"""
make_private.py - move EXISTING proof images on Cloudinary from public to
private (type "authenticated"). Put next to manage.py. Same setup as
fix_media_names.py (CLOUDINARY_* and DATABASE_URL set in PowerShell).

    python make_private.py            # DRY RUN, changes nothing
    python make_private.py --apply    # converts them
"""
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "likhalaya_project.settings")

import django  # noqa: E402

django.setup()

import cloudinary.uploader  # noqa: E402
from orders.models import Order  # noqa: E402

APPLY = "--apply" in sys.argv
done = failed = 0

for order in Order.all_objects.all():
    for field in ("payment_proof", "pickup_proof", "delivery_proof"):
        f = getattr(order, field)
        if not f:
            continue
        pid = f.name
        if not APPLY:
            print(f"[dry] order {order.pk} {field}: {pid}")
            continue
        try:
            cloudinary.uploader.rename(
                pid, pid, type="upload", to_type="authenticated",
                overwrite=True, invalidate=True,
            )
            print(f"OK     order {order.pk} {field}: {pid}")
            done += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAILED order {order.pk} {field}: {pid} -> {e}")
            failed += 1

print(f"\nconverted: {done}, failed: {failed}" if APPLY else "\nDry run only. Add --apply to convert.")