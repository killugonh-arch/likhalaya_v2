from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST
from django.core.cache import cache
from django.db import transaction
from store.models import Product, ProductDesign
from .cart import Cart, calculate_shipping_fee, _max_purchasable
from .forms import CheckoutForm
from .models import Order, OrderItem, GCashQRCode
from .gcash_qr_gen import generate_gcash_qr_png
from .validators import validate_payment_proof, MIN_PROOF_SIZE, MAX_PROOF_SIZE
from likhalaya_project.rate_limit import throttle, check_hourly_limit

# Per-user cap on dynamic QR generation. Each of these views also caches its
# generated PNG bytes for a short window (see below), so under normal use
# (a page loading its own QR once, maybe a manual refresh) this limit is
# never hit — it only kicks in for a scripted loop hammering the endpoint.
GCASH_QR_MAX_PER_HOUR = 120
GCASH_QR_CACHE_SECONDS = 30  # short: amount/reference can change (cart edits)

# Cap on receipt-upload attempts per user per hour (each attempt decodes and
# re-encodes an image up to 2 MB, so unlimited attempts are a CPU/disk risk).
PROOF_UPLOAD_MAX_PER_HOUR = 20


def _proof_upload_allowed(request):
    return check_hourly_limit(f'proof_upload:{request.user.pk}', PROOF_UPLOAD_MAX_PER_HOUR)


def _gcash_qr_throttle_key(request):
    return f'gcash_qr_gen:{request.user.pk if request.user.is_authenticated else "anon"}'

# Session key holding the shipping/contact info the customer entered on the
# checkout form while they're still on the GCash payment step. No Order row
# exists yet at this point.
GCASH_DRAFT_SESSION_KEY = 'gcash_checkout_draft'


def _resolve_gcash_qr_override_url(products):
    """If the order is for exactly one distinct product and that product has
    its own gcash_qr_code uploaded (Admin-controlled, see store/forms.py),
    that specific static image is used instead of the dynamically generated
    QR. Returns None when no such override applies."""
    products = [p for p in products if p is not None]
    distinct_ids = {p.pk for p in products}
    if len(distinct_ids) == 1 and products[0].gcash_qr_code:
        return products[0].gcash_qr_code.url
    return None


def _create_order(request, items, payment_method, form_data, extra=None, finalize=True, cart=None, selected_ids=None):
    """Create the Order + OrderItems for the given items. Shared by the COD
    path (checkout), the GCash path, and Buy Now — `items` is just a plain
    list of item dicts (as produced by Cart.__iter__ / iter_selected /
    get_buy_now_item), so this function has no idea (and doesn't need to
    know) whether they came from the cart or from a standalone Buy Now
    purchase.

    Stock is only deducted when finalize=True. For GCash, finalize=False is
    used while the order is still just a draft holding the uploaded receipt
    — this way, backing out before actually tapping "Confirm Order" leaves
    stock untouched, and the draft stays invisible to My Orders / dashboards
    (see Order.is_finalized / OrderManager).

    Pass `cart` + `selected_ids` only for a normal cart checkout: when
    finalize=True, those cart lines are then removed. Buy Now checkouts
    never touched the cart in the first place, so callers should leave
    these as None and clear the Buy Now session item themselves.

    Raises InsufficientStockError if, at the moment of purchase, live stock
    can no longer cover what's in the cart/buy-now item (e.g. someone else
    bought the last units between add-to-cart and checkout). The caller is
    responsible for catching this and showing the customer a friendly
    message — nothing is written to the database in that case."""
    items = list(items)

    if finalize:
        _assert_stock_available(items)

    subtotal = sum(item['price'] * item['quantity'] for item in items)
    shipping_fee = calculate_shipping_fee(subtotal)
    with transaction.atomic():
        order = Order.all_objects.create(
            user=request.user if request.user.is_authenticated else None,
            full_name=form_data.get('full_name', ''),
            email=form_data.get('email', ''),
            phone=form_data.get('phone', ''),
            address=form_data.get('address', ''),
            city=form_data.get('city', ''),
            province=form_data.get('province', ''),
            zip_code=form_data.get('zip_code', ''),
            notes=form_data.get('notes', ''),
            payment_method=payment_method,
            subtotal=subtotal,
            shipping_fee=shipping_fee,
            total=subtotal + shipping_fee,
            is_finalized=finalize,
            **(extra or {}),
        )
        for item in items:
            OrderItem.objects.create(
                order=order,
                product=item['product'],
                product_name=item['name'],
                product_price=item['price'],
                size=item.get('size', ''),
                design=item.get('design'),
                design_name=item.get('design_name', ''),
                quantity=item['quantity'],
            )
            if finalize:
                design = item.get('design')
                if design:
                    design.deduct_stock(item['quantity'])
                else:
                    p = item['product']
                    p.stock = max(0, p.stock - item['quantity'])
                    p.save()
        if finalize and cart is not None and selected_ids is not None:
            cart.remove_many(selected_ids)
            request.session.pop('checkout_selected_ids', None)
    return order


class InsufficientStockError(Exception):
    """Raised when one or more cart/buy-now items can no longer be fully
    covered by live stock at the moment of purchase — e.g. another customer
    bought the same units between add-to-cart and checkout. Carries the
    list of affected item names so the caller can show a specific message."""
    def __init__(self, unavailable_names):
        self.unavailable_names = unavailable_names
        super().__init__(
            "Insufficient stock for: " + ", ".join(unavailable_names)
        )


def _assert_stock_available(items):
    """Re-check live stock for every item right before it's actually
    purchased. Cart quantities are only clamped against stock at the moment
    an item is *added* to the cart (see orders/cart.py) — nothing
    re-validates that snapshot later, so stock can legitimately run out
    from under an item sitting in someone's cart. Raises
    InsufficientStockError (with no DB writes) if any item's requested
    quantity now exceeds what's actually available."""
    unavailable = []
    for item in items:
        design = item.get('design')
        product = item.get('product')
        available = _max_purchasable(product, design) if product else 0
        if item['quantity'] > available:
            unavailable.append(item.get('name') or (product.name if product else 'Unknown item'))
    if unavailable:
        raise InsufficientStockError(unavailable)


def _finalize_order(order):
    """Turn a GCash draft order (is_finalized=False) into a real one: deduct
    stock for its items and mark it finalized. Does not touch the cart —
    callers still hold their own Cart(request) to clear it/pop the session
    draft key.

    Raises InsufficientStockError (leaving the order untouched, still a
    draft) if live stock can no longer cover the draft's items — e.g. the
    customer sat on the GCash payment screen long enough for someone else
    to buy the same units."""
    items = list(order.items.select_related('product', 'design').all())
    unavailable = []
    for item in items:
        available = _max_purchasable(item.product, item.design) if item.product else 0
        if item.quantity > available:
            unavailable.append(item.design.title if item.design else item.product_name)
    if unavailable:
        raise InsufficientStockError(unavailable)

    with transaction.atomic():
        for item in items:
            if item.design:
                item.design.deduct_stock(item.quantity)
            elif item.product:
                item.product.stock = max(0, item.product.stock - item.quantity)
                item.product.save(update_fields=['stock'])
        order.is_finalized = True
        order.save(update_fields=['is_finalized'])


@require_POST
def cart_add(request, product_id):
    cart = Cart(request)
    product = get_object_or_404(Product, id=product_id, is_active=True)
    buy_now = bool(request.POST.get('buy_now'))

    if buy_now and not request.user.is_authenticated:
        messages.info(request, 'Please create an account to use Buy Now.')
        register_url = reverse('accounts:register')
        return redirect(f'{register_url}?next={product.get_absolute_url()}')

    if buy_now and request.user.is_authenticated and (not request.user.phone or not request.user.address or not request.user.city or not request.user.province):
        messages.warning(request, 'Please add your phone number and complete address to your profile before checking out.')
        profile_url = reverse('accounts:profile')
        return redirect(f'{profile_url}?next={product.get_absolute_url()}')

    quantity = int(request.POST.get('quantity', 1))
    override = request.POST.get('override', False)
    size = request.POST.get('size', '').upper()
    if size not in dict(Product.SIZE_CHOICES):
        size = None

    design = None
    design_id = request.POST.get('design_id')
    if design_id:
        design = ProductDesign.objects.filter(
            id=design_id, product_size__product=product, is_active=True
        ).first()
        if design and not size:
            size = design.product_size.name

    if buy_now:
        # Buy Now must never touch the persistent cart: don't add/merge
        # into cart.cart here. Stash it as a standalone item instead, so
        # whatever's already in the cart is completely unaffected.
        item = cart.set_buy_now(product=product, quantity=quantity, size=size, design=design)
        if item['quantity'] <= 0:
            messages.error(request, 'That selection is currently out of stock.')
            return redirect(product.get_absolute_url())
        request.session.pop('checkout_selected_ids', None)
        request.session['checkout_source'] = 'buy_now'
        request.session.modified = True
        return redirect('orders:checkout')

    key = cart.make_key(product.id, size, design.id if design else None)
    cart.add(product=product, quantity=quantity, override_quantity=bool(override), size=size, design=design)
    if cart.get_quantity(key) == 0:
        messages.error(request, 'That selection is currently out of stock.')
    else:
        messages.success(request, f'"{product.name}" added to cart!')
    referer = request.META.get('HTTP_REFERER', '')
    return redirect(referer if referer else 'store:home')


@require_POST
def cart_update(request, item_key):
    cart = Cart(request)
    line = cart.cart.get(item_key)
    if not line:
        return redirect(request.META.get('HTTP_REFERER') or 'orders:cart_detail')
    product = get_object_or_404(Product, id=line['product_id'])
    action = request.POST.get('action', 'increase')
    current_qty = cart.get_quantity(item_key)
    size = line.get('size') or None
    design = None
    if line.get('design_id'):
        design = ProductDesign.objects.filter(id=line['design_id']).first()
    if action == 'increase':
        cart.add(product=product, quantity=1, override_quantity=False, size=size, design=design)
    elif action == 'decrease' and current_qty > 1:
        cart.add(product=product, quantity=current_qty - 1, override_quantity=True, size=size, design=design)
    referer = request.META.get('HTTP_REFERER', '')
    return redirect(referer if referer else 'orders:cart_detail')


@require_POST
def cart_remove(request, item_key):
    cart = Cart(request)
    cart.remove(item_key)
    messages.info(request, 'Item removed from cart.')
    referer = request.META.get('HTTP_REFERER', '')
    return redirect(referer if referer else 'orders:cart_detail')


def cart_detail(request):
    cart = Cart(request)
    cart_total = cart.get_total_price()
    shipping_fee = calculate_shipping_fee(cart_total)
    amount_for_free_shipping = max(0, 500 - cart_total)
    return render(request, 'orders/cart.html', {
        'cart': cart,
        'cart_items': list(cart),
        'cart_total': cart_total,
        'shipping_fee': shipping_fee,
        'amount_for_free_shipping': amount_for_free_shipping,
    })


@require_POST
def checkout_select(request):
    cart = Cart(request)
    selected_ids = request.POST.getlist('selected_items')
    if not selected_ids:
        messages.warning(request, 'Please select at least one item to checkout.')
        return redirect('orders:cart_detail')

    if not request.user.is_authenticated:
        messages.info(request, 'Please create an account to checkout.')
        register_url = reverse('accounts:register')
        return redirect(f'{register_url}?next={reverse("orders:cart_detail")}')

    request.session['checkout_selected_ids'] = selected_ids
    request.session['checkout_source'] = 'cart'
    request.session.modified = True
    return redirect('orders:checkout')


@cache_control(no_store=True, no_cache=True, must_revalidate=True)
def checkout(request):
    cart = Cart(request)
    checkout_source = request.session.get('checkout_source', 'cart')

    if checkout_source == 'buy_now':
        return _checkout_buy_now(request, cart)

    if len(cart) == 0:
        messages.warning(request, 'Your cart is empty.')
        return redirect('store:shop')

    if not request.user.is_authenticated:
        messages.info(request, 'Please create an account to checkout.')
        register_url = reverse('accounts:register')
        return redirect(f'{register_url}?next={reverse("orders:cart_detail")}')

    all_ids = [str(pid) for pid in cart.cart.keys()]
    raw_selected_ids = request.session.get('checkout_selected_ids') or all_ids
    selected_ids = [pid for pid in raw_selected_ids if pid in all_ids] or all_ids

    if request.user.is_authenticated and (not request.user.phone or not request.user.address or not request.user.city or not request.user.province):
        messages.warning(request, 'Please add your phone number and complete address to your profile before checking out.')
        profile_url = reverse('accounts:profile')
        return redirect(f'{profile_url}?next={reverse("orders:cart_detail")}')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'cod')
        form_data = {
            'full_name': request.POST.get('full_name', ''),
            'email': request.POST.get('email', ''),
            'phone': request.POST.get('phone', ''),
            'address': request.POST.get('address', ''),
            'city': request.POST.get('city', ''),
            'province': request.POST.get('province', ''),
            'zip_code': request.POST.get('zip_code', ''),
            'notes': request.POST.get('notes', ''),
        }

        if payment_method == 'gcash':
            # Don't create the order yet — just remember what the customer
            # entered. The order is only created once they actually send a
            # valid GCash receipt, so backing out here leaves no trace in
            # "My Orders".
            request.session[GCASH_DRAFT_SESSION_KEY] = {
                'form_data': form_data,
                'selected_ids': selected_ids,
                'buy_now': False,
            }
            request.session.modified = True
            return redirect('orders:checkout_review')

        try:
            order = _create_order(request, cart.iter_selected(selected_ids), 'cod', form_data, cart=cart, selected_ids=selected_ids)
        except InsufficientStockError as e:
            messages.error(
                request,
                'Sorry, stock ran out for: ' + ', '.join(e.unavailable_names) +
                '. Please update your cart and try again.'
            )
            return redirect('orders:cart_detail')
        messages.success(request, f'Order {order.order_number} placed! Thank you for supporting PDL artisans.')
        return redirect('orders:order_confirmation', pk=order.pk)

    cart_total = cart.total_price_for(selected_ids)
    shipping_fee = calculate_shipping_fee(cart_total)
    return render(request, 'orders/checkout.html', {
        'cart': cart.iter_selected(selected_ids),
        'cart_total': cart_total,
        'shipping_fee': shipping_fee,
        'grand_total': cart_total + shipping_fee,
        'checkout_source': checkout_source,
    })


def _checkout_buy_now(request, cart):
    """Buy Now checkout: works off the single ad-hoc item stashed in the
    session (see Cart.set_buy_now), never off cart.cart, so anything
    already in the customer's real cart is left completely untouched."""
    buy_now_item = cart.get_buy_now_item()
    if not buy_now_item:
        messages.warning(request, 'That Buy Now item is no longer available.')
        request.session.pop('checkout_source', None)
        return redirect('store:shop')

    if not request.user.is_authenticated:
        messages.info(request, 'Please create an account to use Buy Now.')
        register_url = reverse('accounts:register')
        return redirect(f'{register_url}?next={buy_now_item["product"].get_absolute_url()}')

    if not request.user.phone or not request.user.address or not request.user.city or not request.user.province:
        messages.warning(request, 'Please add your phone number and complete address to your profile before checking out.')
        profile_url = reverse('accounts:profile')
        return redirect(f'{profile_url}?next={buy_now_item["product"].get_absolute_url()}')

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method', 'cod')
        form_data = {
            'full_name': request.POST.get('full_name', ''),
            'email': request.POST.get('email', ''),
            'phone': request.POST.get('phone', ''),
            'address': request.POST.get('address', ''),
            'city': request.POST.get('city', ''),
            'province': request.POST.get('province', ''),
            'zip_code': request.POST.get('zip_code', ''),
            'notes': request.POST.get('notes', ''),
        }

        if payment_method == 'gcash':
            request.session[GCASH_DRAFT_SESSION_KEY] = {
                'form_data': form_data,
                'selected_ids': None,
                'buy_now': True,
            }
            request.session.modified = True
            return redirect('orders:checkout_review')

        try:
            order = _create_order(request, [buy_now_item], 'cod', form_data)
        except InsufficientStockError:
            messages.error(request, 'Sorry, that item just sold out. Please check the product page for availability.')
            cart.clear_buy_now()
            request.session.pop('checkout_source', None)
            return redirect('store:shop')
        cart.clear_buy_now()
        request.session.pop('checkout_source', None)
        messages.success(request, f'Order {order.order_number} placed! Thank you for supporting PDL artisans.')
        return redirect('orders:order_confirmation', pk=order.pk)

    cart_total = buy_now_item['total']
    shipping_fee = calculate_shipping_fee(cart_total)
    return render(request, 'orders/checkout.html', {
        'cart': [buy_now_item],
        'cart_total': cart_total,
        'shipping_fee': shipping_fee,
        'grand_total': cart_total + shipping_fee,
        'checkout_source': 'buy_now',
    })


def buy_now_cancel(request):
    """'Back' from a Buy Now checkout: discard the pending Buy Now item
    (never was in the cart) and send the customer to the Shop — their
    actual cart is left exactly as it was."""
    cart = Cart(request)
    cart.clear_buy_now()
    request.session.pop('checkout_source', None)
    return redirect('store:shop')


def _sync_form_data_from_profile(request, form_data):
    """Pull the latest address/contact info from the user's profile into a
    draft dict, in case they edited their profile mid-checkout. Keeps
    anything the profile doesn't track (like notes) untouched."""
    u = request.user
    form_data['phone'] = u.phone or form_data.get('phone', '')
    form_data['address'] = u.address or form_data.get('address', '')
    form_data['city'] = u.city or form_data.get('city', '')
    form_data['province'] = u.province or form_data.get('province', '')
    form_data['zip_code'] = getattr(u, 'zip_code', '') or form_data.get('zip_code', '')
    return form_data


@cache_control(no_store=True, no_cache=True, must_revalidate=True)
def checkout_review(request):
    """Step 2 of the GCash flow: let the customer review everything they
    entered — and correct their delivery address or profile — before they
    move on to the actual GCash QR/payment step."""
    if not request.user.is_authenticated:
        return redirect('accounts:login')

    draft = request.session.get(GCASH_DRAFT_SESSION_KEY)
    if not draft:
        messages.info(request, 'Please fill in your order details first.')
        return redirect('orders:checkout')

    cart = Cart(request)
    if draft.get('buy_now'):
        buy_now_item = cart.get_buy_now_item()
        if not buy_now_item:
            messages.warning(request, 'That Buy Now item is no longer available.')
            request.session.pop(GCASH_DRAFT_SESSION_KEY, None)
            request.session.pop('checkout_source', None)
            return redirect('store:shop')
        items = [buy_now_item]
    else:
        all_ids = [str(pid) for pid in cart.cart.keys()]
        selected_ids = [pid for pid in draft['selected_ids'] if pid in all_ids]
        if not selected_ids:
            messages.warning(request, 'Your cart changed since you started checkout. Please review your order again.')
            request.session.pop(GCASH_DRAFT_SESSION_KEY, None)
            return redirect('orders:checkout')
        items = list(cart.iter_selected(selected_ids))

    # Pull in any address/contact changes made on the Profile page while
    # the customer was away reviewing/editing their location.
    draft['form_data'] = _sync_form_data_from_profile(request, draft['form_data'])
    request.session[GCASH_DRAFT_SESSION_KEY] = draft
    request.session.modified = True

    cart_total = sum(item['price'] * item['quantity'] for item in items)
    shipping_fee = calculate_shipping_fee(cart_total)

    return render(request, 'orders/checkout_review.html', {
        'cart': items,
        'cart_total': cart_total,
        'shipping_fee': shipping_fee,
        'grand_total': cart_total + shipping_fee,
        'form_data': draft['form_data'],
    })


@cache_control(no_store=True, no_cache=True, must_revalidate=True)
def gcash_payment_pending(request):
    """Step 2 of the GCash flow, before an Order exists. Shows the QR code
    and amount for the draft the customer entered at checkout; only creates
    the real Order once a valid receipt screenshot is uploaded."""
    if not request.user.is_authenticated:
        return redirect('accounts:login')

    draft = request.session.get(GCASH_DRAFT_SESSION_KEY)
    if not draft:
        messages.info(request, 'Please fill in your order details first.')
        return redirect('orders:checkout')

    cart = Cart(request)
    is_buy_now = bool(draft.get('buy_now'))
    if is_buy_now:
        buy_now_item = cart.get_buy_now_item()
        if not buy_now_item:
            messages.warning(request, 'That Buy Now item is no longer available.')
            request.session.pop(GCASH_DRAFT_SESSION_KEY, None)
            request.session.pop('checkout_source', None)
            return redirect('store:shop')
        items = [buy_now_item]
        selected_ids = None
    else:
        all_ids = [str(pid) for pid in cart.cart.keys()]
        selected_ids = [pid for pid in draft['selected_ids'] if pid in all_ids]
        if not selected_ids:
            messages.warning(request, 'Your cart changed since you started checkout. Please review your order again.')
            request.session.pop(GCASH_DRAFT_SESSION_KEY, None)
            return redirect('orders:checkout')
        items = list(cart.iter_selected(selected_ids))

    draft['form_data'] = _sync_form_data_from_profile(request, draft['form_data'])
    request.session[GCASH_DRAFT_SESSION_KEY] = draft
    request.session.modified = True

    cart_total = sum(item['price'] * item['quantity'] for item in items)
    shipping_fee = calculate_shipping_fee(cart_total)
    draft_total = cart_total + shipping_fee

    if request.method == 'POST':
        if not _proof_upload_allowed(request):
            messages.error(request, 'Too many upload attempts. Please wait a while and try again.')
            return redirect('orders:gcash_payment_pending')
        proof = request.FILES.get('payment_proof')
        if not proof:
            messages.error(request, 'Please attach a screenshot of your GCash payment before sending.')
            return redirect('orders:gcash_payment_pending')
        error = validate_payment_proof(proof)
        if error:
            messages.error(request, error)
            return redirect('orders:gcash_payment_pending')

        # Get rid of any earlier abandoned draft for this user before making
        # a new one, so unconfirmed attempts don't pile up in the DB. Delete
        # their receipt files too — queryset.delete() removes DB rows only,
        # which would leave the images orphaned on disk.
        stale_drafts = Order.all_objects.filter(
            user=request.user, payment_method='gcash', is_finalized=False,
        )
        for stale in stale_drafts:
            if stale.payment_proof:
                stale.payment_proof.storage.delete(stale.payment_proof.name)
        stale_drafts.delete()

        order = _create_order(
            request, items, 'gcash', draft['form_data'],
            extra={'payment_proof': proof, 'payment_submitted_at': timezone.now()},
            finalize=False,
        )
        request.session.pop(GCASH_DRAFT_SESSION_KEY, None)
        # Remember whether this draft is a Buy Now order so gcash_finalize
        # knows to clear the Buy Now session item (not touch the cart) once
        # the customer actually confirms it.
        if is_buy_now:
            request.session['gcash_draft_buy_now'] = True
        else:
            request.session.pop('gcash_draft_buy_now', None)
        messages.success(request, 'Verification image received! Review everything and tap Confirm Order to finish.')
        return redirect('orders:gcash_payment', pk=order.pk)

    active_qr = GCashQRCode.objects.filter(status=GCashQRCode.STATUS_ACTIVE_LOCKED).order_by('-created_at').first()
    override_url = _resolve_gcash_qr_override_url([item.get('product') for item in items])
    if override_url:
        qr_image_url = override_url
    else:
        # No per-product override — use a dynamically generated, per-draft
        # QR (amount + reference baked in) instead of the static site QR.
        request.session.setdefault(
            'gcash_pending_ref', f"PEND-{request.user.pk}-{int(timezone.now().timestamp())}"
        )
        qr_image_url = reverse('orders:gcash_qr_image_pending')
    return render(request, 'orders/gcash_payment_pending.html', {
        'active_qr': active_qr,
        'qr_image_url': qr_image_url,
        'draft_total': draft_total,
        'min_proof_kb': MIN_PROOF_SIZE // 1024,
        'max_proof_kb': MAX_PROOF_SIZE // 1024,
    })


@cache_control(no_store=True, no_cache=True, must_revalidate=True)
def gcash_payment(request, pk):
    """Step 4/5: the Order already exists (created with its receipt attached
    in gcash_payment_pending). Lets the customer review order details,
    replace the receipt, and see any address changes made on Profile."""
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    # Use all_objects: the order is normally still an unconfirmed draft
    # (is_finalized=False) at this stage, which the default manager hides.
    order = get_object_or_404(Order.all_objects, pk=pk, user=request.user, payment_method='gcash')

    if request.method == 'POST':
        if not _proof_upload_allowed(request):
            messages.error(request, 'Too many upload attempts. Please wait a while and try again.')
            return redirect('orders:gcash_payment', pk=order.pk)
        proof = request.FILES.get('payment_proof')
        error = None if proof else 'Please attach a screenshot of your GCash payment before sending.'
        if proof and not error:
            error = validate_payment_proof(proof)
        if error:
            messages.error(request, error)
        else:
            old_proof_name = order.payment_proof.name if order.payment_proof else None
            order.payment_proof = proof
            order.payment_submitted_at = timezone.now()
            order.save()
            # The replaced receipt is no longer referenced — remove it from disk.
            if old_proof_name and old_proof_name != order.payment_proof.name:
                order.payment_proof.storage.delete(old_proof_name)
            messages.success(request, 'Verification image received! Review everything and tap Confirm Order to finish.')
        return redirect('orders:gcash_payment', pk=order.pk)

    # Order isn't finalized yet (still awaiting the customer's final
    # "Confirm Order" tap) — safe to pull in any address edits they made
    # on their Profile page while reviewing.
    if not order.is_finalized:
        u = request.user
        changed = False
        for order_field, profile_field in [('phone', 'phone'), ('address', 'address'), ('city', 'city'), ('province', 'province')]:
            new_value = getattr(u, profile_field, '') or ''
            if new_value and getattr(order, order_field) != new_value:
                setattr(order, order_field, new_value)
                changed = True
        zip_value = getattr(u, 'zip_code', '') or ''
        if zip_value and order.zip_code != zip_value:
            order.zip_code = zip_value
            changed = True
        if changed:
            order.save()

    active_qr = GCashQRCode.objects.filter(status=GCashQRCode.STATUS_ACTIVE_LOCKED).order_by('-created_at').first()
    override_url = _resolve_gcash_qr_override_url([item.product for item in order.items.all()])
    qr_image_url = override_url or reverse('orders:gcash_qr_image', args=[order.pk])
    return render(request, 'orders/gcash_payment.html', {
        'order': order,
        'active_qr': active_qr,
        'qr_image_url': qr_image_url,
        'min_proof_kb': MIN_PROOF_SIZE // 1024,
        'max_proof_kb': MAX_PROOF_SIZE // 1024,
    })


def gcash_back_to_checkout(request, pk):
    """'Back to Cart' from the confirm screen: instead of dumping the
    customer into their whole cart, take them to checkout pre-filtered to
    just the items in this draft GCash order, so unrelated cart items don't
    get mixed in."""
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    order = get_object_or_404(Order.all_objects, pk=pk, user=request.user, payment_method='gcash')
    cart = Cart(request)

    if request.session.get('gcash_draft_buy_now'):
        # This draft was a Buy Now purchase, not a cart checkout — restore
        # the ad-hoc Buy Now item (still never touching the real cart) and
        # send them back to the Buy Now checkout, not the cart-based one.
        item = order.items.first()
        if item and item.product_id:
            product = Product.objects.filter(id=item.product_id).first()
            if product:
                cart.set_buy_now(product=product, quantity=item.quantity, size=item.size or None, design=item.design)
        request.session['checkout_source'] = 'buy_now'
        request.session.modified = True
        return redirect('orders:checkout')

    selected_ids = [
        cart.make_key(item.product_id, item.size or None, item.design_id or None)
        for item in order.items.all() if item.product_id
    ]
    request.session['checkout_selected_ids'] = selected_ids
    request.session['checkout_source'] = 'cart'
    request.session.modified = True
    return redirect('orders:checkout')


@require_POST
def gcash_finalize(request, pk):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    order = get_object_or_404(Order.all_objects, pk=pk, user=request.user, payment_method='gcash')

    if not order.payment_proof:
        messages.error(request, 'Please send your GCash payment verification image first.')
        return redirect('orders:gcash_payment', pk=order.pk)

    if not order.is_finalized:
        # This is the actual moment of purchase: only now do we deduct
        # stock and clear the cart. Everything before this (uploading the
        # receipt, viewing this review page, hitting back) left no trace.
        try:
            _finalize_order(order)
        except InsufficientStockError as e:
            messages.error(
                request,
                'Sorry, stock ran out while your GCash payment was pending for: ' +
                ', '.join(e.unavailable_names) +
                '. Your payment proof is saved — please contact support for a refund, '
                'or cancel this order and shop again.'
            )
            return redirect('orders:gcash_payment', pk=order.pk)
        cart = Cart(request)
        if request.session.pop('gcash_draft_buy_now', False):
            cart.clear_buy_now()
            request.session.pop('checkout_source', None)
        else:
            cart.remove_many([str(item.product_id) for item in order.items.all() if item.product_id])
        request.session.pop(GCASH_DRAFT_SESSION_KEY, None)

    messages.success(request, f'Order {order.order_number} placed! Thank you for supporting PDL artisans.')
    return redirect('orders:order_confirmation', pk=order.pk)


def order_confirmation(request, pk):
    order = get_object_or_404(Order, pk=pk)
    status_order = ['pending', 'processing', 'confirmed', 'shipped', 'delivered', 'cancelled']
    reached_status = order.previous_status if order.status == 'cancelled' and order.previous_status else order.status
    status_index = status_order.index(reached_status) + 1 if reached_status in status_order else 1
    return render(request, 'orders/confirmation.html', {'order': order, 'status_index': status_index})


def my_orders(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    orders = Order.objects.filter(user=request.user).prefetch_related('items').order_by('-created_at')
    status_filter = request.GET.get('status', '')
    if status_filter:
        orders = orders.filter(status=status_filter)
    return render(request, 'orders/my_orders.html', {
        'orders': orders,
        'status_filter': status_filter,
        'status_choices': Order.STATUS_CHOICES,
    })


def order_detail(request, pk):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    order = get_object_or_404(Order, pk=pk, user=request.user)
    order.notifications.filter(is_read=False).update(is_read=True)
    status_order = ['pending', 'processing', 'confirmed', 'shipped', 'delivered', 'cancelled']
    reached_status = order.previous_status if order.status == 'cancelled' and order.previous_status else order.status
    status_index = status_order.index(reached_status) + 1 if reached_status in status_order else 1
    return render(request, 'orders/order_detail.html', {
        'order': order,
        'status_index': status_index,
    })


@require_POST
def cancel_order(request, pk):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    order = get_object_or_404(Order, pk=pk, user=request.user)
    if order.status in ['shipped', 'delivered', 'cancelled']:
        messages.error(request, 'This order can no longer be cancelled.')
    else:
        order.previous_status = order.status
        order.status = 'cancelled'
        order.save()
        order.restock_items()
        messages.success(request, f'Order {order.order_number} has been cancelled.')
    return redirect('orders:order_detail', pk=order.pk)


# ─── Dynamic per-transaction GCash QR images ─────────────────────────────
# These views generate a fresh QR image (amount + reference baked in) on
# every request, server-side — the amount/reference is always recomputed
# from the actual draft/Order in the DB or session, never trusted from the
# client, so there's no way to tamper with what the QR shows by editing a
# URL. See orders/gcash_qr_gen.py for how the image itself is built.
@cache_control(no_store=True, no_cache=True, must_revalidate=True)
@throttle(_gcash_qr_throttle_key, GCASH_QR_MAX_PER_HOUR)
def gcash_qr_image_pending(request):
    """Serves the dynamic QR for the not-yet-created GCash draft order."""
    if not request.user.is_authenticated:
        return HttpResponse(status=403)
    draft = request.session.get(GCASH_DRAFT_SESSION_KEY)
    if not draft:
        return HttpResponse(status=404)

    cart = Cart(request)
    if draft.get('buy_now'):
        buy_now_item = cart.get_buy_now_item()
        items = [buy_now_item] if buy_now_item else []
    else:
        all_ids = [str(pid) for pid in cart.cart.keys()]
        selected_ids = [pid for pid in draft['selected_ids'] if pid in all_ids]
        items = list(cart.iter_selected(selected_ids))
    if not items:
        return HttpResponse(status=404)

    cart_total = sum(item['price'] * item['quantity'] for item in items)
    shipping_fee = calculate_shipping_fee(cart_total)
    amount = cart_total + shipping_fee

    reference = request.session.get(
        'gcash_pending_ref', f"PEND-{request.user.pk}-{int(timezone.now().timestamp())}"
    )

    # Same amount+reference always draws the identical PNG, so a short
    # server-side cache avoids redoing the QR-encode + image-draw work on
    # every page load/refresh — the no-store headers above only stop the
    # *browser* from caching a stale QR, they don't affect this.
    cache_key = f'gcash_qr_png_pending:{reference}:{amount}'
    png_bytes = cache.get(cache_key)
    if png_bytes is None:
        png_bytes = generate_gcash_qr_png(amount, reference)
        cache.set(cache_key, png_bytes, GCASH_QR_CACHE_SECONDS)
    return HttpResponse(png_bytes, content_type='image/png')


@cache_control(no_store=True, no_cache=True, must_revalidate=True)
@throttle(_gcash_qr_throttle_key, GCASH_QR_MAX_PER_HOUR)
def gcash_qr_image(request, pk):
    """Serves the dynamic QR for an already-created GCash order/draft."""
    if not request.user.is_authenticated:
        return HttpResponse(status=403)
    order = get_object_or_404(Order.all_objects, pk=pk, user=request.user, payment_method='gcash')

    cache_key = f'gcash_qr_png_order:{order.pk}:{order.total}'
    png_bytes = cache.get(cache_key)
    if png_bytes is None:
        png_bytes = generate_gcash_qr_png(order.total, order.order_number)
        cache.set(cache_key, png_bytes, GCASH_QR_CACHE_SECONDS)
    return HttpResponse(png_bytes, content_type='image/png')