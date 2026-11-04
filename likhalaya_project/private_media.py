"""
likhalaya_project/private_media.py

Serves private proof images only to: the order's customer, the assigned
courier, and admin/staff. Everyone else gets 404.
"""
import requests
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse

from orders.models import Order

FIELD_BY_FOLDER = {
    'payment_proofs': 'payment_proof',
    'pickup_proofs': 'pickup_proof',
    'delivery_proofs': 'delivery_proof',
}


@login_required
def private_media(request, path):
    clean = path.replace('\\', '/').lstrip('/')
    folder = clean[len('media/'):] if clean.startswith('media/') else clean
    field = FIELD_BY_FOLDER.get(folder.split('/', 1)[0])
    if not field:
        raise Http404

    order = Order.all_objects.filter(**{field: path}).first()
    if not order:
        raise Http404

    user = request.user
    allowed = (
        user.is_superuser
        or getattr(user, 'role', '') in ('admin', 'staff')
        or order.user_id == user.id
        or (getattr(user, 'role', '') == 'courier' and order.assigned_courier_id == user.id)
    )
    if not allowed:
        raise Http404

    try:
        upstream = requests.get(default_storage.signed_url(path), timeout=15)
    except requests.RequestException:
        raise Http404
    if upstream.status_code != 200:
        raise Http404

    response = HttpResponse(
        upstream.content,
        content_type=upstream.headers.get('Content-Type', 'image/jpeg'),
    )
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response