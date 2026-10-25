from urllib.parse import urlsplit, urlunsplit, urlencode, parse_qsl

from django.contrib import messages

from store.models import Product, ProductDesign

PENDING_CART_SESSION_KEY = 'pending_cart_action'


def stash_pending_action(request, product, quantity, size, design, buy_now, next_url):
    """Remember what a not-logged-in visitor tried to add/buy, so it can be
    applied right after they log in (or finish signing up)."""
    request.session[PENDING_CART_SESSION_KEY] = {
        'product_id': product.id,
        'quantity': quantity,
        'size': size or '',
        'design_id': design.id if design else None,
        'buy_now': bool(buy_now),
        'next': next_url,
    }
    request.session.modified = True


def apply_pending_action(request):
    """Call right after a successful login. Adds the remembered item to the
    cart (or sets up Buy Now) and returns the URL to redirect to, or None
    if there was nothing pending."""
    data = request.session.pop(PENDING_CART_SESSION_KEY, None)
    if not data:
        return None
    request.session.modified = True

    product = Product.objects.filter(id=data.get('product_id'), is_active=True).first()
    if not product:
        messages.warning(request, 'The product you picked is no longer available.')
        return None

    design = None
    if data.get('design_id'):
        design = ProductDesign.objects.filter(
            id=data['design_id'], product_size__product=product, is_active=True
        ).first()
    size = data.get('size') or None
    quantity = max(1, int(data.get('quantity') or 1))
    origin = data.get('next') or ''  # page the visitor clicked from (home, shop, product...)
    product_url = origin or product.get_absolute_url()

    # Both Buy Now and Add to Cart behave the same after login: go back to
    # the page they clicked on and reopen that product's picker with their
    # earlier choices filled in, so they confirm it themselves.
    parts = urlsplit(product_url)
    drop = ('reopen_buy_now', 'reopen_cart', 'bn_size', 'bn_design', 'bn_qty')
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in drop]
    query.append(('reopen_buy_now' if data.get('buy_now') else 'reopen_cart', product.id))
    if size:
        query.append(('bn_size', size))
    if design:
        query.append(('bn_design', design.id))
    if quantity > 1:
        query.append(('bn_qty', quantity))
    return urlunsplit(('', '', parts.path, urlencode(query), ''))