import json
import re
import csv
import calendar
import functools
from io import BytesIO
from decimal import Decimal, InvalidOperation
from datetime import timedelta, date

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import zipfile

from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from .chat_helpers import chat_inbox
from django.db.models import Sum, Count, Q, Avg, Case, When, Value, IntegerField
from django.db.models.functions import TruncMonth, TruncDate, Coalesce, ExtractYear
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator
from django.urls import reverse
from django.views.decorators.http import require_POST


def _safe_next(request, next_url, fallback):
    """Only follow a `next` value if it's a same-site, safe redirect target.
    Prevents an attacker from crafting a POST with next=https://evil.example
    to redirect a staff member off-site after an action."""
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback

from store.models import Product, Category, ContactMessage, LivelihoodVideo, ProductImage, ProductSize, ProductDesign, MessageReply
from store.forms import ProductForm, ProductImageFormSet
from likhalaya_project.rate_limit import throttle

# Exports do real work (unfiltered table pull + in-memory workbook build
# with per-row styling), so cap how often one staff account can trigger
# them — a runaway script/refresh loop shouldn't be able to repeatedly
# force that cost.
EXPORT_MAX_PER_HOUR = 20


def _export_throttle_key(request):
    return f'dashboard_export:{request.user.pk}'
from orders.models import Order, OrderItem, Notification, OrderStatusError, GCashQRCode, GCashQRRemovalRequest
from accounts.models import CustomUser, ActivityLog
from accounts.activity import log_activity
from dashboard.models import MonthlyPeriod, Expense


def _parse_variant_post(post):
    """Parse the Size → Design fields (size-<i>-*, design-<i>-<j>-*)
    submitted by the product form. Returns (sizes, errors); does NOT touch
    the database. A size is just Small/Medium/Large — it has no price of
    its own (that always comes from the Product's Pricing & Inventory
    fields). A design is a photo + title only. `sizes` is a list of dicts:
      {'index', 'id', 'name', 'is_active', 'delete', 'designs': [
          {'index', 'id', 'title', 'is_active', 'delete'}
      ]}
    """
    errors = []
    valid_names = {'S', 'M', 'L'}
    size_indices = sorted(set(
        int(m.group(1)) for k in post
        for m in [re.match(r'^size-(\d+)-name$', k)] if m
    ))

    sizes = []
    for si in size_indices:
        p = f'size-{si}-'
        delete = bool(post.get(p + 'DELETE'))
        name = (post.get(p + 'name') or '').strip().upper()
        size_entry = {
            'index': si, 'id': post.get(p + 'id') or None,
            'name': name, 'is_active': bool(post.get(p + 'is_active')),
            'delete': delete, 'designs': [],
        }
        if not delete and name not in valid_names:
            errors.append(f'Size #{si + 1}: choose Small, Medium, or Large.')

        design_indices = sorted(set(
            int(m.group(1)) for k in post
            for m in [re.match(rf'^design-{si}-(\d+)-title$', k)] if m
        ))
        for di in design_indices:
            dp = f'design-{si}-{di}-'
            d_delete = bool(post.get(dp + 'DELETE'))
            title = (post.get(dp + 'title') or '').strip()
            color = (post.get(dp + 'color') or '').strip()
            if not d_delete and not delete and not title:
                errors.append(f'Size "{name}": every design needs a title.')
            raw_stock = (post.get(dp + 'stock') or '').strip()
            try:
                stock = max(0, int(raw_stock)) if raw_stock else 0
            except (TypeError, ValueError):
                stock = 0
                if not d_delete and not delete:
                    errors.append(f'Size "{name}" · "{title or "design"}": quantity must be a whole number.')
            size_entry['designs'].append({
                'index': di, 'id': post.get(dp + 'id') or None,
                'title': title, 'color': color,
                'is_active': bool(post.get(dp + 'is_active')),
                'delete': d_delete, 'stock': stock,
            })
        sizes.append(size_entry)

    return sizes, errors


def _size_panels(product):
    """Always return exactly 3 panels — Small, Medium, Large — in that
    fixed order, each paired with its existing ProductSize (or None if the
    merchant hasn't added anything under that tier yet). This is what lets
    the "Sizes & Designs" section in the product form show fixed S/M/L
    slots instead of a size picker: the sizes already exist conceptually
    via the Pricing & Inventory fields, so here it's designs-only."""
    codes = [('S', 'Small'), ('M', 'Medium'), ('L', 'Large')]
    existing = {}
    if product and product.pk:
        for s in product.sizes.all():
            existing.setdefault(s.name, s)
    return [{'code': code, 'label': label, 'size': existing.get(code)} for code, label in codes]


def _apply_variants(product, sizes, files):
    """Create/update/delete ProductSize + ProductDesign rows for `product`
    from the parsed `sizes` structure (see _parse_variant_post). Must run
    inside a transaction, and only after `_parse_variant_post` reported no
    errors."""
    for s in sizes:
        if s['delete']:
            if s['id']:
                ProductSize.objects.filter(pk=s['id'], product=product).delete()
            continue

        has_any_design = any(not d['delete'] for d in s['designs'])
        if not s['id'] and not s['is_active'] and not has_any_design:
            # A fixed Small/Medium/Large panel the merchant never touched
            # (left inactive, no designs added) — don't create a blank
            # ProductSize row for it.
            continue

        if s['id']:
            size_obj = get_object_or_404(ProductSize, pk=s['id'], product=product)
            size_obj.name = s['name']
            size_obj.is_active = s['is_active']
            size_obj.order = s['index']
            size_obj.save()
        else:
            size_obj = ProductSize.objects.create(
                product=product, name=s['name'],
                is_active=s['is_active'], order=s['index'],
            )

        for d in s['designs']:
            if d['delete']:
                if d['id']:
                    ProductDesign.objects.filter(pk=d['id'], product_size=size_obj).delete()
                continue

            image_file = files.get(f"design-{s['index']}-{d['index']}-image")
            # Each design carries its OWN quantity, entered directly in the
            # form — it is never derived from another field. The product's
            # overall stock is instead derived FROM these (see the
            # `product.recalculate_stock()` call after this loop).
            if d['id']:
                design_obj = get_object_or_404(ProductDesign, pk=d['id'], product_size=size_obj)
                design_obj.title = d['title']
                design_obj.color = d['color']
                design_obj.is_active = d['is_active']
                design_obj.order = d['index']
                design_obj.stock = d['stock']
                if image_file:
                    design_obj.image = image_file
                design_obj.save()
            else:
                ProductDesign.objects.create(
                    product_size=size_obj, title=d['title'], color=d['color'],
                    image=image_file, is_active=d['is_active'], order=d['index'], stock=d['stock'],
                )

    # The admin never edits total stock directly — it's always the sum of
    # every active design's own quantity, recalculated here after every
    # create/update/delete pass over the size/design tree.
    product.recalculate_stock()


# ─── Decorators ────────────────────────────────────────────────────────────────
def staff_required(view_func):
    @functools.wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff_user():
            messages.error(request, 'Access denied. Staff only.')
            return redirect('store:home')
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_required(view_func):
    @functools.wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin_user():
            messages.error(request, 'Access denied. Admins only.')
            return redirect('dashboard:home')
        return view_func(request, *args, **kwargs)
    return wrapper


def courier_required(view_func):
    """Allows our own delivery couriers, plus admins (who can act on behalf
    of any courier). Regular staff accounts are NOT couriers."""
    @functools.wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_courier_user() or request.user.is_admin_user()):
            messages.error(request, 'Access denied. Delivery couriers only.')
            return redirect('store:home')
        return view_func(request, *args, **kwargs)
    return wrapper


def _xlsx_bytes(wb):
    """
    Save an openpyxl Workbook to bytes with [Content_Types].xml and _rels/.rels
    placed first in the zip archive. openpyxl doesn't guarantee this ordering,
    and while Microsoft Excel is lenient about it, WPS Office's parser is not —
    files that open fine in Excel can fail to open ("Unable to open file") in
    WPS unless the standard OPC entry order is respected. Re-packaging the zip
    this way makes the export open cleanly in both.
    """
    raw = BytesIO()
    wb.save(raw)
    raw.seek(0)

    src = zipfile.ZipFile(raw)
    names = src.namelist()
    priority = ['[Content_Types].xml', '_rels/.rels', 'xl/workbook.xml', 'xl/_rels/workbook.xml.rels']
    ordered = [n for n in priority if n in names] + [n for n in names if n not in priority]

    out = BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in ordered:
            z.writestr(n, src.read(n))
    out.seek(0)
    return out.getvalue()


# ─── Dashboard Home ─────────────────────────────────────────────────────────────
@staff_required
def dashboard_home(request):
    now = timezone.now()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)

    # ── True calendar-month boundaries (not a rolling 30-day window) ──
    # "This month" = 1st of current month through now.
    # "Last month" = 1st through last day of the previous month.
    # Nothing is ever deleted — these are just date filters on the same Order table,
    # so the numbers naturally roll over to ₱0 on the 1st of a new month.
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = this_month_start - timedelta(microseconds=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    this_month_revenue = Order.objects.filter(
        status='delivered', created_at__gte=this_month_start
    ).aggregate(t=Sum('total'))['t'] or 0
    last_month_revenue = Order.objects.filter(
        status='delivered', created_at__gte=last_month_start, created_at__lt=this_month_start
    ).aggregate(t=Sum('total'))['t'] or 0

    # % change vs last month, for a "up/down from last month" indicator on the card
    if last_month_revenue:
        revenue_change_pct = round(((this_month_revenue - last_month_revenue) / last_month_revenue) * 100, 1)
    else:
        revenue_change_pct = 100.0 if this_month_revenue else 0.0

    stats = {
        'total_orders': Order.objects.count(),
        'orders_today': Order.objects.filter(created_at__date=now.date()).count(),
        'total_revenue': Order.objects.filter(status='delivered').aggregate(t=Sum('total'))['t'] or 0,
        'monthly_revenue': this_month_revenue,
        'last_month_revenue': last_month_revenue,
        'revenue_change_pct': revenue_change_pct,
        'pending_orders': Order.objects.filter(status='pending').count(),
        'confirmed_orders': Order.objects.filter(status='confirmed').count(),
        'delivered_orders': Order.objects.filter(status='delivered').count(),
        'cancelled_orders': Order.objects.filter(status='cancelled').count(),
        'total_products': Product.objects.filter(is_active=True).count(),
        'low_stock': Product.objects.filter(stock__lte=5, is_active=True).count(),
        'out_of_stock': Product.objects.filter(stock=0, is_active=True).count(),
        'total_customers': CustomUser.objects.filter(role='customer').count(),
        'total_staff': CustomUser.objects.filter(role='staff').count(),
        'new_customers': CustomUser.objects.filter(role='customer', created_at__gte=thirty_days_ago).count(),
        'total_messages': ContactMessage.objects.count(),
        'unread_messages': ContactMessage.objects.filter(is_read=False).count(),
        'total_categories': Category.objects.filter(is_active=True).count(),
    }

    # Chart 1: last 7 days orders (trend — is business picking up?)
    daily_orders = []
    daily_labels = []
    for i in range(6, -1, -1):
        d = (now - timedelta(days=i)).date()
        cnt = Order.objects.filter(created_at__date=d).count()
        daily_orders.append(cnt)
        daily_labels.append(d.strftime('%b %d'))

    # Chart 2: order status distribution (only statuses that actually have orders,
    # so the legend/chart isn't cluttered with zero-count slices)
    status_display = dict(Order.STATUS_CHOICES)
    status_colors = {
        'pending': '#f39c12', 'confirmed': '#3498db', 'processing': '#1abc9c',
        'shipped': '#9b59b6', 'delivered': '#27ae60', 'cancelled': '#e74c3c',
    }
    status_counts = {s[0]: Order.objects.filter(status=s[0]).count() for s in Order.STATUS_CHOICES}
    status_counts = {k: v for k, v in status_counts.items() if v > 0}

    recent_orders = Order.objects.select_related('user').prefetch_related('items').order_by('-created_at')[:8]
    low_stock_products = Product.objects.filter(stock__lte=5, is_active=True).select_related('category')[:5]
    recent_customers = CustomUser.objects.filter(role='customer').order_by('-created_at')[:5]

    ctx = {
        'stats': stats,
        'recent_orders': recent_orders,
        'low_stock_products': low_stock_products,
        'recent_customers': recent_customers,
        'chart_daily_labels': json.dumps(daily_labels),
        'chart_daily_orders': json.dumps(daily_orders),
        'chart_status_labels': json.dumps([status_display[k] for k in status_counts.keys()]),
        'chart_status_data': json.dumps(list(status_counts.values())),
        'chart_status_colors': json.dumps([status_colors[k] for k in status_counts.keys()]),
    }
    return render(request, 'dashboard/home.html', ctx)


# ─── Messages ───────────────────────────────────────────────────────────────────
@staff_required
def message_list(request):
    messages_qs = ContactMessage.objects.order_by('-created_at')
    read_filter = request.GET.get('read', '')
    search = request.GET.get('q', '')
    if read_filter in {'true', 'false'}:
        messages_qs = messages_qs.filter(is_read=(read_filter == 'true'))
    if search:
        messages_qs = messages_qs.filter(Q(name__icontains=search) | Q(subject__icontains=search) | Q(email__icontains=search))
    paginator = Paginator(messages_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'dashboard/messages/list.html', {
        'messages_list': page_obj,
        'page_obj': page_obj,
        'read_filter': read_filter,
        'search': search,
        'chat_rows': chat_inbox(search, read_filter) if page_obj.number == 1 else [],
    })


@staff_required
def message_mark_all_read(request):
    if request.method == 'POST':
        updated = ContactMessage.objects.filter(is_read=False).update(is_read=True)
        if updated:
            messages.success(request, f'Marked {updated} message(s) as read.')
        else:
            messages.info(request, 'No unread messages.')
    return redirect(_safe_next(request, request.POST.get('next'), 'dashboard:message_list'))


@staff_required
def message_detail(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    if request.method == 'POST':
        if request.POST.get('form') == 'reply':
            body = request.POST.get('reply_body', '').strip()
            if body:
                MessageReply.objects.create(
                    thread=msg,
                    staff=request.user,
                    is_staff_reply=True,
                    body=body,
                    is_read_by_staff=True,
                    is_read_by_customer=False,
                )
                if msg.customer_id:
                    Notification.objects.create(
                        user=msg.customer,
                        contact_message=msg,
                        message=f'You have a new reply to your inquiry: "{msg.subject}"',
                    )
                messages.success(request, 'Reply sent.')
            return redirect('dashboard:message_detail', pk=pk)

        new_status = request.POST.get('status')
        if new_status in dict(ContactMessage.STATUS_CHOICES):
            msg.status = new_status
        msg.staff_notes = request.POST.get('staff_notes', msg.staff_notes)
        msg.save(update_fields=['status', 'staff_notes'])
        messages.success(request, 'Request updated.')
        return redirect('dashboard:message_detail', pk=pk)

    if not msg.is_read:
        msg.is_read = True
        msg.save(update_fields=['is_read'])
    msg.replies.filter(is_staff_reply=False, is_read_by_staff=False).update(is_read_by_staff=True)

    # Build one merged, chronological conversation covering every inquiry this
    # customer account has ever sent (not just this one), so staff can see
    # the whole history in a single thread. Guest/unlinked requests (no
    # customer account) fall back to showing just this one inquiry.
    if msg.customer_id:
        account_threads = list(
            ContactMessage.objects.filter(customer_id=msg.customer_id)
            .order_by('created_at')
            .prefetch_related('replies__staff')
        )
    else:
        account_threads = [msg]

    timeline = []
    for thread in account_threads:
        timeline.append({
            'is_staff_reply': False,
            'sender_name': thread.name,
            'body': thread.message,
            'created_at': thread.created_at,
            'subject': thread.subject,
            'is_current': thread.pk == msg.pk,
        })
        for reply in thread.replies.all():
            if reply.is_staff_reply:
                sender_name = (reply.staff.get_full_name() if reply.staff else '') or (reply.staff.username if reply.staff else 'Staff')
            else:
                sender_name = thread.name
            timeline.append({
                'is_staff_reply': reply.is_staff_reply,
                'sender_name': sender_name,
                'body': reply.body,
                'created_at': reply.created_at,
                'subject': thread.subject,
                'is_current': thread.pk == msg.pk,
                'is_read_by_customer': reply.is_read_by_customer,
            })
    timeline.sort(key=lambda e: e['created_at'])

    last_staff_reply = msg.replies.filter(is_staff_reply=True).order_by('-created_at').first()
    handled_by = last_staff_reply.staff if last_staff_reply and last_staff_reply.staff else None
    last_activity_at = timeline[-1]['created_at'] if timeline else msg.created_at

    # Sidebar inbox list — same search/filter behaviour as the plain list view,
    # so switching between conversations doesn't lose context.
    inbox_qs = ContactMessage.objects.order_by('-created_at').prefetch_related('replies')
    read_filter = request.GET.get('read', '')
    search = request.GET.get('q', '')
    if read_filter in {'true', 'false'}:
        inbox_qs = inbox_qs.filter(is_read=(read_filter == 'true'))
    if search:
        inbox_qs = inbox_qs.filter(Q(name__icontains=search) | Q(subject__icontains=search) | Q(email__icontains=search))
    inbox_messages = inbox_qs[:50]

    return render(request, 'dashboard/messages/detail.html', {
        'message': msg,
        'replies': msg.replies.all(),
        'timeline': timeline,
        'account_thread_count': len(account_threads),
        'inbox_messages': inbox_messages,
        'handled_by': handled_by,
        'last_activity_at': last_activity_at,
        'read_filter': read_filter,
        'search': search,
        'chat_rows': chat_inbox(search, read_filter),
    })


@staff_required
def message_delete(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    if request.method == 'POST':
        msg.archive(by_user=request.user)
        messages.success(request, 'Message moved to the Archive.')
        return redirect('dashboard:message_list')
    return redirect('dashboard:message_detail', pk=pk)


@admin_required
def message_restore(request, pk):
    msg = get_object_or_404(ContactMessage.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        msg.restore()
        log_activity(request, 'restore', f'Restored message "{msg.subject}"',
                     resource='ContactMessage', resource_label=msg.subject)
        messages.success(request, f'Message "{msg.subject}" restored.')
    return redirect('dashboard:archive')


@admin_required
def message_delete_permanent(request, pk):
    msg = get_object_or_404(ContactMessage.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        subject = msg.subject
        log_activity(request, 'delete', f'Permanently deleted message "{subject}"',
                     resource='ContactMessage', resource_label=subject)
        msg.delete()
        messages.success(request, f'Message "{subject}" permanently deleted.')
    return redirect('dashboard:archive')


# ─── Products ───────────────────────────────────────────────────────────────────
@staff_required
def product_list(request):
    products = Product.objects.select_related('category').order_by('-created_at')
    q = request.GET.get('q', '')
    cat_filter = request.GET.get('category', '')
    status_filter = request.GET.get('status', '')
    if q:
        products = products.filter(Q(name__icontains=q) | Q(artisan_name__icontains=q))
    if cat_filter:
        products = products.filter(category__id=cat_filter)
    if status_filter == 'active':
        products = products.filter(is_active=True)
    elif status_filter == 'inactive':
        products = products.filter(is_active=False)
    elif status_filter == 'low_stock':
        products = products.filter(stock__lte=5)
    paginator = Paginator(products, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'dashboard/products/list.html', {
        'products': page_obj,
        'page_obj': page_obj,
        'q': q,
        'categories': Category.objects.filter(is_active=True),
        'cat_filter': cat_filter,
        'status_filter': status_filter,
    })


@staff_required
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related('category').prefetch_related(
            'extra_images', 'sizes__designs'
        ),
        pk=pk
    )
    gallery_by_size = {'General': [], 'Small': [], 'Medium': [], 'Large': []}
    size_labels = {'S': 'Small', 'M': 'Medium', 'L': 'Large'}
    for img in product.extra_images.all():
        label = size_labels.get(img.size, 'General')
        gallery_by_size[label].append(img)

    # Build the Size → Designs tree for the redesigned Variants section,
    # plus dynamic summary counts (sizes/designs/total stock). Nothing here
    # is hard-coded — it's all derived from this product's own rows.
    size_rows = list(product.sizes.all().order_by('order', 'id'))
    total_designs = 0
    total_stock = 0
    for s in size_rows:
        designs = list(s.designs.all().order_by('order', 'id'))
        s.design_list = designs
        s.design_count = len(designs)
        s.stock_total = sum(d.stock for d in designs)
        total_designs += s.design_count
        total_stock += s.stock_total

    return render(request, 'dashboard/products/detail.html', {
        'product': product,
        'gallery_by_size': gallery_by_size,
        'size_rows': size_rows,
        'variant_summary': {
            'size_count': len(size_rows),
            'design_count': total_designs,
            'total_stock': total_stock,
        },
    })


@staff_required
def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, user=request.user)
        image_formset = ProductImageFormSet(request.POST, request.FILES, prefix='images')
        variant_sizes, variant_errors = _parse_variant_post(request.POST)
        if form.is_valid() and image_formset.is_valid() and not variant_errors:
            with transaction.atomic():
                product = form.save()
                image_formset.instance = product
                image_formset.save()
                _apply_variants(product, variant_sizes, request.FILES)
            log_activity(request, 'create', f'Created product "{product.name}"',
                         resource='Product', resource_label=product.name,
                         new_value=f'{product.price_display} · stock {product.stock}')
            messages.success(request, f'Product "{product.name}" created successfully!')
            return redirect('dashboard:product_list')
        for err in variant_errors:
            messages.error(request, err)
    else:
        form = ProductForm(user=request.user)
        image_formset = ProductImageFormSet(prefix='images')
    return render(request, 'dashboard/products/form.html', {
        'form': form, 'image_formset': image_formset, 'title': 'Add Product',
        'size_panels': _size_panels(None),
    })


@staff_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        # Snapshot every trackable field before the form overwrites them,
        # so the activity log reports whichever ones actually changed
        # (not just price/stock — description, active status,
        # category, artisan, and image all count too).
        old_values = {
            'name': product.name,
            'description': product.description,
            'category': product.category.name if product.category else '(none)',
            'price_min': product.price_min,
            'price_medium': product.price_medium,
            'price_max': product.price_max,
            'stock': product.stock,
            'is_active': product.is_active,
            'artisan_name': product.artisan_name,
            'image': product.image.name if product.image else '',
        }
        form = ProductForm(request.POST, request.FILES, instance=product, user=request.user)
        image_formset = ProductImageFormSet(request.POST, request.FILES, instance=product, prefix='images')
        variant_sizes, variant_errors = _parse_variant_post(request.POST)
        if form.is_valid() and image_formset.is_valid() and not variant_errors:
            with transaction.atomic():
                form.save()
                image_formset.save()
                _apply_variants(product, variant_sizes, request.FILES)

            new_values = {
                'name': product.name,
                'description': product.description,
                'category': product.category.name if product.category else '(none)',
                'price_min': product.price_min,
                'price_medium': product.price_medium,
                'price_max': product.price_max,
                'stock': product.stock,
                'is_active': product.is_active,
                    'artisan_name': product.artisan_name,
                'image': product.image.name if product.image else '',
            }

            field_labels = {
                'name': 'Name',
                'description': 'Description',
                'category': 'Category',
                'price_min': 'Min price',
                'price_medium': 'Medium price',
                'price_max': 'Max price',
                'stock': 'Stock',
                'is_active': 'Active status',
                'artisan_name': 'Artisan',
                'image': 'Image',
            }

            changes = []
            for field, old_val in old_values.items():
                new_val = new_values[field]
                if old_val != new_val:
                    if field == 'image':
                        old_display = old_val.rsplit('/', 1)[-1] if old_val else '(none)'
                        new_display = new_val.rsplit('/', 1)[-1] if new_val else '(none)'
                    elif field == 'description':
                        # Full text is kept here; the detail page truncates
                        # long values visually and offers a "see all" toggle.
                        old_display = old_val or '(empty)'
                        new_display = new_val or '(empty)'
                    elif field == 'is_active':
                        old_display = 'On' if old_val else 'Off'
                        new_display = 'On' if new_val else 'Off'
                    else:
                        old_display = old_val
                        new_display = new_val
                    changes.append(f'{field_labels[field]}: {old_display} → {new_display}')

            previous_value = '; '.join(changes) if changes else 'No fields changed'
            new_value = f'{len(changes)} field(s) updated' if changes else 'No fields changed'

            log_activity(request, 'update', f'Updated product "{product.name}"',
                         resource='Product', resource_label=product.name,
                         previous_value=previous_value,
                         new_value=new_value)
            messages.success(request, f'Product "{product.name}" updated!')
            return redirect('dashboard:product_list')
        for err in variant_errors:
            messages.error(request, err)
        if not form.is_valid():
            for field, field_errors in form.errors.items():
                label = form.fields[field].label if field in form.fields else field
                for fe in field_errors:
                    messages.error(request, f'{label}: {fe}')
        if not image_formset.is_valid():
            for fe in image_formset.non_form_errors():
                messages.error(request, fe)
            for i, img_form in enumerate(image_formset.forms):
                for field, field_errors in img_form.errors.items():
                    for fe in field_errors:
                        messages.error(request, f'Photo #{i + 1} — {field}: {fe}')
    else:
        form = ProductForm(instance=product, user=request.user)
        image_formset = ProductImageFormSet(instance=product, prefix='images')
    return render(request, 'dashboard/products/form.html', {
        'form': form, 'image_formset': image_formset,
        'title': 'Edit Product', 'product': product,
        'size_panels': _size_panels(product),
    })


@admin_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        name = product.name
        old_snapshot = f'{product.price_display} · stock {product.stock}'
        product.archive(by_user=request.user)
        log_activity(request, 'delete', f'Archived product "{name}"',
                     resource='Product', resource_label=name,
                     previous_value=old_snapshot)
        messages.success(request, f'Product "{name}" moved to Archive. You can restore it anytime.')
        return redirect('dashboard:product_list')
    return render(request, 'dashboard/products/confirm_delete.html', {'product': product})


@admin_required
def product_restore(request, pk):
    product = get_object_or_404(Product.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        product.restore()
        log_activity(request, 'restore', f'Restored product "{product.name}"',
                     resource='Product', resource_label=product.name)
        messages.success(request, f'Product "{product.name}" restored.')
    return redirect('dashboard:archive')


@admin_required
def product_delete_permanent(request, pk):
    product = get_object_or_404(Product.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        name = product.name
        log_activity(request, 'delete', f'Permanently deleted product "{name}"',
                     resource='Product', resource_label=name)
        product.delete()
        messages.success(request, f'Product "{name}" permanently deleted.')
    return redirect('dashboard:archive')


# ─── Orders ─────────────────────────────────────────────────────────────────────
@staff_required
def order_list(request):
    orders = Order.objects.select_related('user').prefetch_related('items').order_by('-created_at')
    status = request.GET.get('status', '')
    search = request.GET.get('q', '')
    payment = request.GET.get('payment', '')
    if status:
        orders = orders.filter(status=status)
    if search:
        orders = orders.filter(Q(full_name__icontains=search) | Q(email__icontains=search) | Q(pk__icontains=search))
    if payment:
        orders = orders.filter(payment_method=payment)
    paginator = Paginator(orders, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'dashboard/orders/list.html', {
        'orders': page_obj,
        'page_obj': page_obj,
        'status_filter': status,
        'search': search,
        'payment_filter': payment,
        'status_choices': Order.STATUS_CHOICES,
        'payment_choices': Order.PAYMENT_CHOICES,
    })


@staff_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    # Staff can also act as couriers (they can ship orders themselves), so
    # the assign dropdown includes both roles, not just role='courier'.
    couriers = CustomUser.objects.filter(role__in=['courier', 'staff'], is_active=True).order_by('first_name', 'username')
    return render(request, 'dashboard/orders/detail.html', {
        'order': order,
        'status_choices': Order.STATUS_CHOICES,
        'couriers': couriers,
    })


def _log_and_notify(request, order, old_status, new_status, note_message=None):
    if new_status != old_status:
        log_activity(
            request, 'status_change',
            f'Order {order.order_number} status: {old_status} → {new_status}',
            resource='Order', resource_label=order.order_number,
            previous_value=old_status, new_value=new_status,
        )
    if note_message and order.user:
        Notification.objects.create(user=order.user, order=order, message=note_message)


@staff_required
@require_POST
def order_start_processing(request, pk):
    """Task action: 'Start Processing'. Pending -> Processing, no dropdown."""
    order = get_object_or_404(Order, pk=pk)
    old_status = order.status
    try:
        order.start_processing()
    except OrderStatusError as e:
        messages.error(request, str(e))
    else:
        _log_and_notify(request, order, old_status, order.status)
        messages.success(request, f'Order {order.order_number} is now being processed.')
    return redirect('dashboard:order_detail', pk=pk)


@staff_required
@require_POST
def order_mark_ready(request, pk):
    """Task action: 'Mark Ready for Delivery'. Processing -> Confirmed."""
    order = get_object_or_404(Order, pk=pk)
    old_status = order.status
    try:
        order.mark_ready_for_delivery()
    except OrderStatusError as e:
        messages.error(request, str(e))
    else:
        _log_and_notify(
            request, order, old_status, order.status,
            note_message=f'Your order {order.order_number} has been confirmed and is ready for delivery.',
        )
        messages.success(request, f'Order {order.order_number} is confirmed and ready for delivery.')
    return redirect('dashboard:order_detail', pk=pk)


@staff_required
@require_POST
def order_assign_courier(request, pk):
    """Assign one of our delivery personnel to handle pickup/delivery for
    this order. Does not change the order status by itself."""
    order = get_object_or_404(Order, pk=pk)
    courier_id = request.POST.get('courier_id')
    courier = CustomUser.objects.filter(pk=courier_id, role__in=['courier', 'staff']).first() if courier_id else None
    if courier_id and not courier:
        messages.error(request, 'Please select a valid courier.')
        return redirect('dashboard:order_detail', pk=pk)
    try:
        order.assign_courier(courier)
    except OrderStatusError as e:
        messages.error(request, str(e))
    else:
        log_activity(
            request, 'update',
            f'Order {order.order_number} assigned to courier: {courier.get_full_name() if courier else "unassigned"}',
            resource='Order', resource_label=order.order_number,
        )
        messages.success(request, f'Order {order.order_number} assigned to {courier.get_full_name() if courier else "no courier"}.')
    return redirect('dashboard:order_detail', pk=pk)


@staff_required
@require_POST
def order_cancel(request, pk):
    """Explicit, separate Cancel action — never part of the status dropdown."""
    order = get_object_or_404(Order, pk=pk)
    old_status = order.status
    try:
        order.cancel()
    except OrderStatusError as e:
        messages.error(request, str(e))
    else:
        _log_and_notify(request, order, old_status, order.status)
        messages.success(request, f'Order {order.order_number} has been cancelled.')
    return redirect('dashboard:order_detail', pk=pk)


# ─── Courier delivery workflow ──────────────────────────────────────────────
@courier_required
def courier_order_list(request):
    """A courier only ever sees orders assigned to them. An admin browsing
    this page sees every order that currently needs a courier action."""
    orders = Order.objects.filter(status__in=['confirmed', 'shipped']).select_related('assigned_courier', 'user')
    if request.user.is_courier_user():
        orders = orders.filter(assigned_courier=request.user)
    orders = orders.prefetch_related('items').order_by('-created_at')
    return render(request, 'dashboard/courier/list.html', {'orders': orders})


@courier_required
def courier_order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.user.is_courier_user() and order.assigned_courier_id != request.user.id:
        messages.error(request, 'This order is not assigned to you.')
        return redirect('dashboard:courier_order_list')

    if request.method == 'POST':
        action = request.POST.get('action')
        old_status = order.status
        if action == 'confirm_pickup':
            proof = request.FILES.get('pickup_proof')
            try:
                order.confirm_pickup(proof)
            except OrderStatusError as e:
                messages.error(request, str(e))
            else:
                _log_and_notify(
                    request, order, old_status, order.status,
                    note_message=f'Good news! Your order {order.order_number} has been shipped and is on its way.',
                )
                messages.success(request, f'Pickup confirmed — order {order.order_number} is now Shipped.')
        elif action == 'confirm_delivery':
            proof = request.FILES.get('delivery_proof')
            try:
                order.confirm_delivery(proof)
            except OrderStatusError as e:
                messages.error(request, str(e))
            else:
                _log_and_notify(
                    request, order, old_status, order.status,
                    note_message=f'Your order {order.order_number} has been delivered. Enjoy!',
                )
                messages.success(request, f'Delivery confirmed — order {order.order_number} is now Delivered.')
        return redirect('dashboard:courier_order_detail', pk=pk)

    return render(request, 'dashboard/courier/detail.html', {'order': order})


@staff_required
@throttle(_export_throttle_key, EXPORT_MAX_PER_HOUR)
def order_export_csv(request):
    """Formal, print-ready Excel export of the Orders list — same sober
    black/white/gray document styling as the Financial Report export,
    with a letterhead, generated-on line, and a signature block so it
    reads as an official paper record rather than a colored dashboard view."""
    orders = Order.objects.prefetch_related('items').order_by('-created_at')
    now = timezone.now()

    # ── Styling constants (formal black/white/gray document palette) ──
    BLACK = '000000'
    DARK_GRAY = '333333'
    MID_GRAY = '666666'
    LIGHT_GRAY = 'F2F2F2'
    HEADER_GRAY = 'D9D9D9'
    WHITE = 'FFFFFF'

    title_font = Font(name='Calibri', size=18, bold=True, color=BLACK)
    subtitle_font = Font(name='Calibri', size=10, italic=True, color=MID_GRAY)
    meta_font = Font(name='Calibri', size=10, bold=True, color=BLACK)
    header_font = Font(name='Calibri', size=10, bold=True, color=BLACK)
    body_font = Font(name='Calibri', size=10, color=DARK_GRAY)
    status_font = Font(name='Calibri', size=10, bold=True, color=BLACK)
    sign_label_font = Font(name='Calibri', size=9, color=MID_GRAY)

    header_fill = PatternFill('solid', fgColor=HEADER_GRAY)
    zebra_fill = PatternFill('solid', fgColor=LIGHT_GRAY)
    white_fill = PatternFill('solid', fgColor=WHITE)

    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    double_bottom = Border(bottom=Side(style='double', color=BLACK))
    signature_line = Border(top=Side(style='thin', color=BLACK))
    center = Alignment(horizontal='center', vertical='center')
    left_align = Alignment(horizontal='left', vertical='center')

    wb = Workbook()
    ws = wb.active
    ws.title = 'Orders'
    ws.sheet_view.showGridLines = False

    columns = [
        ('Order #', 14), ('Customer', 20), ('Email', 26), ('Phone', 14),
        ('Status', 13), ('Payment', 16), ('Subtotal', 12), ('Shipping', 12),
        ('Total', 12), ('Date', 18),
    ]
    last_col_letter = get_column_letter(len(columns))
    for i, (_, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    row = 1

    # ── Letterhead ──
    ws.merge_cells(f'A{row}:{last_col_letter}{row}')
    c = ws[f'A{row}']
    c.value = 'LIKHALAYA'
    c.font = title_font
    c.alignment = center
    ws.row_dimensions[row].height = 26
    row += 1

    ws.merge_cells(f'A{row}:{last_col_letter}{row}')
    c = ws[f'A{row}']
    c.value = 'PDL Market — Official Orders Record'
    c.font = Font(name='Calibri', size=11, bold=True, color=DARK_GRAY)
    c.alignment = center
    row += 1

    ws.merge_cells(f'A{row}:{last_col_letter}{row}')
    c = ws[f'A{row}']
    c.value = f'Generated {now.strftime("%B %d, %Y at %I:%M %p")} — {orders.count()} order(s) on record'
    c.font = subtitle_font
    c.alignment = center
    row += 1

    # Double rule under the letterhead, like a formal document header
    for col_idx in range(1, len(columns) + 1):
        ws.cell(row=row, column=col_idx).border = double_bottom
    row += 2

    header_row = row
    for col_idx, (label, _) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border
    ws.row_dimensions[header_row].height = 20
    ws.freeze_panes = f'A{header_row + 1}'
    row = header_row + 1

    for i, o in enumerate(orders):
        fill = zebra_fill if i % 2 else white_fill
        values = [
            o.order_number, o.full_name, o.email, o.phone,
            o.get_status_display().upper(),
            o.get_payment_method_display(),
            float(o.subtotal), float(o.shipping_fee), float(o.total),
            timezone.localtime(o.created_at).replace(tzinfo=None),
        ]
        for col_idx, val in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col_idx, value=val)
            cell.font = status_font if col_idx == 5 else body_font
            cell.fill = fill
            cell.border = border
            if col_idx in (7, 8, 9):
                cell.number_format = '"₱"#,##0.00'
            elif col_idx == 10:
                cell.number_format = 'yyyy-mm-dd hh:mm'
            cell.alignment = center
        row += 1

    ws.auto_filter.ref = f'A{header_row}:{last_col_letter}{row - 1}'

    # ── Certification / signature block — gives the export the feel of
    # a formal paper record that a coordinator can print and sign ──
    row += 2
    ws.merge_cells(f'A{row}:{last_col_letter}{row}')
    cert = ws[f'A{row}']
    cert.value = ('This document certifies the orders on record as of the generation date above. '
                  'Figures reflect the system at the time of export.')
    cert.font = subtitle_font
    cert.alignment = center
    row += 3

    sig_col_span = max(len(columns) // 2, 1)
    left_start, left_end = 'A', get_column_letter(sig_col_span)
    right_start, right_end = get_column_letter(sig_col_span + 1), last_col_letter

    ws.merge_cells(f'{left_start}{row}:{left_end}{row}')
    ws.merge_cells(f'{right_start}{row}:{right_end}{row}')
    for col in range(1, sig_col_span + 1):
        ws.cell(row=row, column=col).border = signature_line
    for col in range(sig_col_span + 1, len(columns) + 1):
        ws.cell(row=row, column=col).border = signature_line
    row += 1

    ws.merge_cells(f'{left_start}{row}:{left_end}{row}')
    lc = ws[f'{left_start}{row}']
    lc.value = 'Prepared by (Coordinator / Staff)'
    lc.font = sign_label_font
    lc.alignment = center
    ws.merge_cells(f'{right_start}{row}:{right_end}{row}')
    rc = ws[f'{right_start}{row}']
    rc.value = 'Verified by (Administrator)'
    rc.font = sign_label_font
    rc.alignment = center
    row += 2

    ws.merge_cells(f'A{row}:{last_col_letter}{row}')
    footer = ws[f'A{row}']
    footer.value = 'Likhalaya PDL Market — Confidential internal orders export'
    footer.font = Font(name='Calibri', size=8, italic=True, color='AAAAAA')
    footer.alignment = center

    ws.print_area = f'A1:{last_col_letter}{row}'
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    buffer_bytes = _xlsx_bytes(wb)
    response = HttpResponse(
        buffer_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f'Likhalaya_Orders_{now.strftime("%Y%m%d")}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ─── Users ──────────────────────────────────────────────────────────────────────
@admin_required
def user_list(request):
    role_order = Case(
        When(role='admin', then=Value(0)),
        When(role='staff', then=Value(1)),
        When(role='customer', then=Value(2)),
        default=Value(3),
        output_field=IntegerField(),
    )
    users = CustomUser.objects.annotate(role_rank=role_order).order_by('role_rank', '-created_at')
    search = request.GET.get('q', '')
    role_filter = request.GET.get('role', '')
    if search:
        users = users.filter(Q(username__icontains=search) | Q(first_name__icontains=search) |
                             Q(last_name__icontains=search) | Q(email__icontains=search))
    if role_filter:
        users = users.filter(role=role_filter)
    paginator = Paginator(users, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'dashboard/users/list.html', {
        'users': page_obj,
        'page_obj': page_obj,
        'search': search,
        'role_filter': role_filter,
        'role_choices': CustomUser.ROLE_CHOICES,
    })


@admin_required
def user_detail(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    from orders.models import Order
    all_orders = Order.objects.filter(user=user)
    user_orders = all_orders.order_by('-created_at')[:10]
    order_stats = all_orders.aggregate(
        total_orders=Count('id'),
        completed_orders=Count('id', filter=Q(status='delivered')),
        pending_orders=Count('id', filter=Q(status__in=['pending', 'processing', 'confirmed', 'shipped'])),
        total_spent=Sum('total', filter=Q(status='delivered')),
    )
    return render(request, 'dashboard/users/detail.html', {
        'profile_user': user,
        'user_orders': user_orders,
        'order_stats': order_stats,
    })


@admin_required
def user_toggle_active(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    if request.method == 'POST':
        old_active = user.is_active
        user.is_active = not user.is_active
        user.save()
        status = 'activated' if user.is_active else 'deactivated'
        log_activity(request, 'update', f'{status.capitalize()} user "{user.username}"',
                     resource='User', resource_label=user.username,
                     previous_value='Active' if old_active else 'Inactive',
                     new_value='Active' if user.is_active else 'Inactive')
        messages.success(request, f'User {user.username} has been {status}.')
    return redirect('dashboard:user_list')


@admin_required
def user_delete(request, pk):
    user = get_object_or_404(CustomUser, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "You can't archive your own account.")
        return redirect('dashboard:user_list')
    if user.is_admin_user():
        remaining_admins = CustomUser.objects.filter(Q(role='admin') | Q(is_superuser=True)).exclude(pk=user.pk).count()
        if remaining_admins == 0:
            messages.error(request, "You can't archive the last remaining admin account.")
            return redirect('dashboard:user_list')
    if request.method == 'POST':
        name = user.username
        role_label = user.get_role_display()
        user.archive(by_user=request.user)
        log_activity(request, 'delete', f'Archived {role_label.lower()} account "{name}"',
                     resource='User', resource_label=name,
                     previous_value=role_label)
        messages.success(request, f'Account "{name}" moved to Archive. You can restore it anytime.')
        return redirect('dashboard:user_list')
    return render(request, 'dashboard/users/confirm_delete.html', {'profile_user': user})


@admin_required
def user_restore(request, pk):
    user = get_object_or_404(CustomUser.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        user.restore()
        log_activity(request, 'restore', f'Restored account "{user.username}"',
                     resource='User', resource_label=user.username)
        messages.success(request, f'Account "{user.username}" restored.')
    return redirect('dashboard:archive')


@admin_required
def user_delete_permanent(request, pk):
    user = get_object_or_404(CustomUser.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        username = user.username
        log_activity(request, 'delete', f'Permanently deleted account "{username}"',
                     resource='User', resource_label=username)
        user.delete()
        messages.success(request, f'Account "{username}" permanently deleted.')
    return redirect('dashboard:archive')


# ─── Archive ────────────────────────────────────────────────────────────────────
@admin_required
def archive(request):
    tab = request.GET.get('tab', 'products')
    products = Product.all_objects.filter(is_deleted=True).select_related('deleted_by', 'category').order_by('-deleted_at')
    categories = Category.all_objects.filter(is_deleted=True).select_related('deleted_by').order_by('-deleted_at')
    customers = CustomUser.all_objects.filter(is_deleted=True, role='customer').select_related('deleted_by').order_by('-deleted_at')
    staff = CustomUser.all_objects.filter(is_deleted=True).exclude(role='customer').select_related('deleted_by').order_by('-deleted_at')
    videos = LivelihoodVideo.all_objects.filter(is_deleted=True).select_related('deleted_by').order_by('-deleted_at')
    contact_messages = ContactMessage.all_objects.filter(is_deleted=True).select_related('deleted_by').order_by('-deleted_at')
    return render(request, 'dashboard/archive/list.html', {
        'tab': tab,
        'products': products,
        'categories': categories,
        'customers': customers,
        'staff': staff,
        'videos': videos,
        'contact_messages': contact_messages,
        'counts': {
            'products': products.count(),
            'categories': categories.count(),
            'customers': customers.count(),
            'staff': staff.count(),
            'videos': videos.count(),
            'messages': contact_messages.count(),
        },
    })


# ─── Activity Log ───────────────────────────────────────────────────────────────
def _format_duration(td):
    """Human-friendly duration string, e.g. '2 min', '1h 14m', '3d 2h'."""
    if td is None:
        return None
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f'{max(total_seconds, 0)}s'
    minutes = total_seconds // 60
    if minutes < 60:
        return f'{minutes} min'
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f'{hours}h {minutes}m' if minutes else f'{hours}h'
    days, hours = divmod(hours, 24)
    return f'{days}d {hours}h' if hours else f'{days}d'


def _build_activity_sessions(logs):
    """
    Groups a chronological (ascending) iterable of ActivityLog rows into one
    "session" per staff login: a session starts at 'login', ends at the next
    'logout' for that same username, and collects every action performed
    in between. This turns the old one-row-per-event log into one card per
    login session, with the individual actions nested inside it.

    Sessions with no matching login (actions/logout that started before the
    filtered window) and sessions with no matching logout yet (still signed
    in) are both included.
    """
    open_sessions = {}   # username -> in-progress session dict
    sessions = []

    def new_session(log, login_time=None, logout_time=None):
        return {
            'username': log.username,
            'role': log.role,
            'user_id': log.user_id,
            'login_time': login_time,
            'login_log_id': log.id if login_time else None,
            'logout_time': logout_time,
            'logout_log_id': log.id if logout_time else None,
            'ip': log.ip_address,
            'actions': [],
        }

    for log in logs:
        key = log.username or f'user_{log.user_id}'
        if log.action == 'login':
            # Previous session for this user never saw a logout (e.g. browser
            # closed) — close it out as-is before starting the new one.
            if key in open_sessions:
                sessions.append(open_sessions.pop(key))
            open_sessions[key] = new_session(log, login_time=log.timestamp)
        elif log.action == 'logout':
            sess = open_sessions.pop(key, None) or new_session(log)
            sess['logout_time'] = log.timestamp
            sess['logout_log_id'] = log.id
            sess['ip'] = log.ip_address
            sessions.append(sess)
        else:
            sess = open_sessions.setdefault(key, new_session(log))
            sess['actions'].append(log)
            sess['ip'] = log.ip_address

    # Anything still open means that staff member hasn't logged out yet.
    sessions.extend(open_sessions.values())

    for s in sessions:
        s['actions'].sort(key=lambda a: a.timestamp, reverse=True)
        s['action_count'] = len(s['actions'])
        # A session card links to *some* real ActivityLog row for its
        # "view details" button — prefer the login event, then the most
        # recent action, then the logout event.
        s['detail_log_id'] = (
            s['login_log_id'] or (s['actions'][0].id if s['actions'] else None) or s['logout_log_id']
        )
        if s['login_time'] and s['logout_time']:
            s['duration_display'] = _format_duration(s['logout_time'] - s['login_time'])
        elif s['login_time'] and not s['logout_time']:
            s['duration_display'] = _format_duration(timezone.now() - s['login_time'])
        else:
            s['duration_display'] = None
        if s['login_time']:
            s['sort_time'] = s['login_time']
        elif s['actions']:
            s['sort_time'] = s['actions'][-1].timestamp  # actions are desc-sorted; [-1] is earliest
        else:
            s['sort_time'] = s['logout_time']

    sessions.sort(key=lambda s: s['sort_time'], reverse=True)
    return sessions


@admin_required
def activity_log(request):
    STAFF_ROLES = ['admin', 'staff']

    search = request.GET.get('q', '')
    staff_filter = request.GET.get('staff', '')
    action_filter = request.GET.get('action', '')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')

    # This page is the STAFF activity log — customer logins/actions are
    # tracked elsewhere and shouldn't clutter it, so every query below is
    # scoped to staff/admin accounts only.
    staff_usernames = set(
        CustomUser.objects.filter(role__in=STAFF_ROLES).values_list('username', flat=True)
    )

    base_qs = ActivityLog.objects.filter(Q(role__in=STAFF_ROLES) | Q(username__in=staff_usernames))
    if date_from:
        base_qs = base_qs.filter(timestamp__date__gte=date_from)
    if date_to:
        base_qs = base_qs.filter(timestamp__date__lte=date_to)

    # Failed logins have no reliable staff account (the username may not
    # even exist), so they're tracked separately rather than folded into a
    # session card. Still restricted to attempts against known staff
    # usernames, to keep this page staff-only.
    failed_logins = base_qs.filter(action='login_failed')
    if search:
        failed_logins = failed_logins.filter(Q(username__icontains=search) | Q(ip_address__icontains=search))
    failed_logins = failed_logins.order_by('-timestamp')[:10]

    session_logs = base_qs.exclude(action='login_failed')
    if staff_filter:
        session_logs = session_logs.filter(username=staff_filter)
    if search:
        session_logs = session_logs.filter(
            Q(username__icontains=search) | Q(description__icontains=search) | Q(ip_address__icontains=search)
        )

    sessions = _build_activity_sessions(session_logs.order_by('timestamp'))

    if action_filter:
        sessions = [s for s in sessions if any(a.action == action_filter for a in s['actions'])]

    # Group sessions by user so the main list shows one card per staff
    # member (not one card per login session) — clicking a card opens
    # that user's full history via activity_log_user.
    user_groups = {}
    for s in sessions:
        key = s['username'] or f"user_{s['user_id']}"
        g = user_groups.setdefault(key, {
            'username': s['username'],
            'role': s['role'],
            'user_id': s['user_id'],
            'session_count': 0,
            'action_count': 0,
            'is_active_now': False,
            'latest_sort_time': s['sort_time'],
            'latest_session': s,
        })
        g['session_count'] += 1
        g['action_count'] += s['action_count']
        if s['logout_time'] is None and s['login_time']:
            g['is_active_now'] = True
        if s['sort_time'] and (not g['latest_sort_time'] or s['sort_time'] > g['latest_sort_time']):
            g['latest_sort_time'] = s['sort_time']
            g['latest_session'] = s

    user_rows = sorted(user_groups.values(), key=lambda g: g['latest_sort_time'] or timezone.now(), reverse=True)

    today = timezone.localdate()
    stats = {
        'total_sessions': len(sessions),
        'sessions_today': sum(1 for s in sessions if s['login_time'] and s['login_time'].date() == today),
        'active_now': sum(1 for s in sessions if s['logout_time'] is None),
        'failed_today': base_qs.filter(action='login_failed', timestamp__date=today).count(),
    }

    staff_choices = list(
        ActivityLog.objects.filter(Q(role__in=STAFF_ROLES) | Q(username__in=staff_usernames))
        .exclude(username='').values_list('username', flat=True).distinct().order_by('username')
    )

    paginator = Paginator(user_rows, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'dashboard/activity/list.html', {
        'user_rows': page_obj,
        'page_obj': page_obj,
        'failed_logins': failed_logins,
        'search': search,
        'staff_filter': staff_filter,
        'action_filter': action_filter,
        'date_from': date_from,
        'date_to': date_to,
        'action_choices': [c for c in ActivityLog.ACTION_CHOICES if c[0] not in ('login', 'logout', 'login_failed')],
        'staff_choices': staff_choices,
        'stats': stats,
    })


@admin_required
@throttle(_export_throttle_key, EXPORT_MAX_PER_HOUR)
def activity_log_export_csv(request):
    STAFF_ROLES = ['admin', 'staff']
    staff_usernames = set(
        CustomUser.objects.filter(role__in=STAFF_ROLES).values_list('username', flat=True)
    )
    logs = ActivityLog.objects.filter(
        Q(role__in=STAFF_ROLES) | Q(username__in=staff_usernames)
    ).order_by('-timestamp')

    search = request.GET.get('q', '')
    staff_filter = request.GET.get('staff', '')
    action_filter = request.GET.get('action', '')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')
    if search:
        logs = logs.filter(Q(username__icontains=search) | Q(description__icontains=search) |
                            Q(ip_address__icontains=search))
    if staff_filter:
        logs = logs.filter(username=staff_filter)
    if action_filter:
        logs = logs.filter(action=action_filter)
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    response = HttpResponse(content_type='text/csv')
    now = timezone.now()
    response['Content-Disposition'] = f'attachment; filename="Likhalaya_ActivityLog_{now.strftime("%Y%m%d")}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'User', 'Role', 'Action', 'Description', 'Resource', 'Previous Value',
                      'New Value', 'Status', 'IP Address'])
    for log in logs:
        writer.writerow([
            timezone.localtime(log.timestamp).strftime('%Y-%m-%d %H:%M:%S'),
            log.username, log.role, log.get_action_display(), log.description,
            f'{log.resource} — {log.resource_label}'.strip(' —') if (log.resource or log.resource_label) else '',
            log.previous_value, log.new_value, log.get_status_display(), log.ip_address or '',
        ])
    return response


@admin_required
def activity_log_detail(request, pk):
    STAFF_ROLES = ['admin', 'staff']
    staff_usernames = set(
        CustomUser.objects.filter(role__in=STAFF_ROLES).values_list('username', flat=True)
    )
    log = get_object_or_404(
        ActivityLog.objects.filter(Q(role__in=STAFF_ROLES) | Q(username__in=staff_usernames)),
        pk=pk,
    )

    # Multi-field updates (e.g. category/product edits) are stored as
    # "Field: old → new; Field2: old2 → new2" in previous_value. Split
    # that into individual rows here so the template can render a clean
    # list instead of one long wrapped string.
    field_changes = []
    if log.previous_value and ': ' in log.previous_value and ' → ' in log.previous_value:
        parts = [p.strip() for p in log.previous_value.split('; ') if p.strip()]
        all_parsed = True
        for part in parts:
            if ': ' not in part or ' → ' not in part:
                all_parsed = False
                break
            label, rest = part.split(': ', 1)
            old_val, new_val = rest.split(' → ', 1)
            field_changes.append({'label': label, 'old': old_val, 'new': new_val})
        if not all_parsed:
            field_changes = []

    # For image fields, resolve the stored filenames into actual media
    # URLs (based on which resource logged the change) so the detail
    # page can render thumbnails instead of just the filename text.
    image_folder = {'Product': 'products/', 'Category': 'categories/'}.get(log.resource)
    if image_folder:
        for change in field_changes:
            if change['label'] == 'Image':
                if change['old'] and change['old'] != '(none)':
                    change['old_url'] = settings.MEDIA_URL + image_folder + change['old']
                if change['new'] and change['new'] != '(none)':
                    change['new_url'] = settings.MEDIA_URL + image_folder + change['new']

    return render(request, 'dashboard/activity/detail.html', {'log': log, 'field_changes': field_changes})


@admin_required
def activity_log_user(request, username):
    """
    Full activity history for a single staff member, reached by clicking
    their name on the main Activity Log page (opens in a new window).
    Every row here links through to activity_log_detail for that entry.
    """
    STAFF_ROLES = ['admin', 'staff']
    staff_usernames = set(
        CustomUser.objects.filter(role__in=STAFF_ROLES).values_list('username', flat=True)
    )
    all_logs = ActivityLog.objects.filter(
        Q(role__in=STAFF_ROLES) | Q(username__in=staff_usernames),
        username=username,
    ).order_by('-timestamp')

    latest = all_logs.first()

    logs = all_logs
    search = request.GET.get('q', '')
    action_filter = request.GET.get('action', '')
    status_filter = request.GET.get('status', '')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')

    if search:
        logs = logs.filter(Q(description__icontains=search) | Q(resource_label__icontains=search) | Q(resource__icontains=search))
    if action_filter:
        logs = logs.filter(action=action_filter)
    if status_filter:
        logs = logs.filter(status=status_filter)
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    stats = all_logs.aggregate(
        total=Count('id'),
        successful=Count('id', filter=Q(status='success')),
        failed=Count('id', filter=Q(status='failed')),
        logins=Count('id', filter=Q(action='login')),
        updates=Count('id', filter=Q(action='update')),
        orders_processed=Count('id', filter=Q(resource='Order')),
    )

    paginator = Paginator(logs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Day-group labels ("Today" / "Yesterday" / date) for the timeline view —
    # computed here since Django templates can't do "yesterday" comparisons.
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    for log in page_obj:
        log_date = timezone.localtime(log.timestamp).date()
        if log_date == today:
            log.day_label = 'Today'
        elif log_date == yesterday:
            log.day_label = 'Yesterday'
        else:
            log.day_label = log_date.strftime('%B %d, %Y')

    return render(request, 'dashboard/activity/user_list.html', {
        'username': username,
        'role': latest.role if latest else '',
        'last_active': latest.timestamp if latest else None,
        'logs': page_obj,
        'page_obj': page_obj,
        'search': search,
        'action_filter': action_filter,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'action_choices': [c for c in ActivityLog.ACTION_CHOICES if c[0] != 'login_failed'],
        'status_choices': ActivityLog.STATUS_CHOICES,
        'total_count': logs.count(),
        'stats': stats,
    })


# ─── Categories ─────────────────────────────────────────────────────────────────
@staff_required
def category_list(request):
    cats = Category.objects.annotate(product_count=Count('products')).order_by('order', 'name')
    return render(request, 'dashboard/categories/list.html', {'categories': cats})


@admin_required
def category_create(request):
    from store.forms import CategoryForm
    if request.method == 'POST':
        form = CategoryForm(request.POST, request.FILES)
        if form.is_valid():
            cat = form.save()
            log_activity(request, 'create', f'Created category "{cat.name}"',
                         resource='Category', resource_label=cat.name)
            messages.success(request, 'Category created.')
            return redirect('dashboard:category_list')
    else:
        form = CategoryForm()
    return render(request, 'dashboard/categories/form.html', {'form': form, 'title': 'Add Category'})


@staff_required
def category_edit(request, pk):
    from store.forms import CategoryForm
    cat = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        # Snapshot every trackable field before the form overwrites them,
        # so the activity log can report whichever ones actually changed
        # (name, description, order, active status, or the image).
        old_values = {
            'name': cat.name,
            'description': cat.description,
            'order': cat.order,
            'is_active': cat.is_active,
            'image': cat.image.name if cat.image else '',
        }
        form = CategoryForm(request.POST, request.FILES, instance=cat)
        if form.is_valid():
            form.save()

            new_values = {
                'name': cat.name,
                'description': cat.description,
                'order': cat.order,
                'is_active': cat.is_active,
                'image': cat.image.name if cat.image else '',
            }

            field_labels = {
                'name': 'Name',
                'description': 'Description',
                'order': 'Order',
                'is_active': 'Active status',
                'image': 'Image',
            }

            changes = []
            for field, old_val in old_values.items():
                new_val = new_values[field]
                if old_val != new_val:
                    if field == 'image':
                        old_display = old_val.rsplit('/', 1)[-1] if old_val else '(none)'
                        new_display = new_val.rsplit('/', 1)[-1] if new_val else '(none)'
                    elif field == 'description':
                        old_display = old_val or '(empty)'
                        new_display = new_val or '(empty)'
                    elif field == 'is_active':
                        old_display = 'On' if old_val else 'Off'
                        new_display = 'On' if new_val else 'Off'
                    else:
                        old_display = old_val
                        new_display = new_val
                    changes.append(f'{field_labels[field]}: {old_display} → {new_display}')

            previous_value = '; '.join(changes) if changes else 'No fields changed'
            new_value = f'{len(changes)} field(s) updated' if changes else 'No fields changed'

            log_activity(request, 'update', f'Updated category "{cat.name}"',
                         resource='Category', resource_label=cat.name,
                         previous_value=previous_value, new_value=new_value)
            messages.success(request, 'Category updated.')
            return redirect('dashboard:category_list')
    else:
        form = CategoryForm(instance=cat)
    return render(request, 'dashboard/categories/form.html', {'form': form, 'title': 'Edit Category', 'category': cat})


@admin_required
def category_delete(request, pk):
    cat = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        cat_name = cat.name
        cat.archive(by_user=request.user)
        log_activity(request, 'delete', f'Archived category "{cat_name}"',
                     resource='Category', resource_label=cat_name,
                     previous_value=cat_name)
        messages.success(request, f'Category "{cat_name}" moved to Archive. You can restore it anytime.')
        return redirect('dashboard:category_list')
    return render(request, 'dashboard/categories/confirm_delete.html', {'category': cat})


@admin_required
def category_restore(request, pk):
    cat = get_object_or_404(Category.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        cat.restore()
        log_activity(request, 'restore', f'Restored category "{cat.name}"',
                     resource='Category', resource_label=cat.name)
        messages.success(request, f'Category "{cat.name}" restored.')
    return redirect('dashboard:archive')


@admin_required
def category_delete_permanent(request, pk):
    cat = get_object_or_404(Category.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        name = cat.name
        log_activity(request, 'delete', f'Permanently deleted category "{name}"',
                     resource='Category', resource_label=name)
        cat.delete()
        messages.success(request, f'Category "{name}" permanently deleted.')
    return redirect('dashboard:archive')


# ─── Reports ────────────────────────────────────────────────────────────────
# ─── PDL Financial Reports ──────────────────────────────────────────────────
#
# Business rule (confirmed): PDL sharing is based on PRODUCT INCOME
# (Order.subtotal) only. Shipping fees (Order.shipping_fee) are always
# reported separately and never enter the PDL calculation. The system
# CALCULATES and REPORTS the PDL Share Amount only — actual distribution to
# individual PDLs is handled manually by the client, outside this system.
#
# Revenue recognition: an order counts toward a given month if its
# delivery_confirmed_at falls in that month. A small number of legacy
# delivered orders have a NULL delivery_confirmed_at (see audit — a since-
# patched API endpoint used to bypass Order.confirm_delivery()); those fall
# back to created_at so they aren't silently dropped from every report, and
# the count of such orders is surfaced in the UI as a data-quality note
# rather than blended in silently.

def _delivered_orders_for_month(year, month):
    """Delivered orders recognized as revenue for the given year/month."""
    return (Order.objects.filter(status='delivered')
            .annotate(revenue_date=Coalesce('delivery_confirmed_at', 'created_at'))
            .filter(revenue_date__year=year, revenue_date__month=month))


def _financial_summary(year, month):
    orders_qs = _delivered_orders_for_month(year, month)
    agg = orders_qs.aggregate(
        product_income=Sum('subtotal'),
        shipping_income=Sum('shipping_fee'),
        gross_total=Sum('total'),
        order_count=Count('id'),
    )
    payment_breakdown = list(
        orders_qs.values('payment_method')
        .annotate(
            product_income=Sum('subtotal'),
            shipping_income=Sum('shipping_fee'),
            total=Sum('total'),
            orders=Count('id'),
        )
        .order_by('payment_method')
    )
    payment_display = dict(Order.PAYMENT_CHOICES)
    for row in payment_breakdown:
        row['payment_method_label'] = payment_display.get(row['payment_method'], row['payment_method'])

    return {
        'product_income': agg['product_income'] or Decimal('0'),
        'shipping_income': agg['shipping_income'] or Decimal('0'),
        'gross_total': agg['gross_total'] or Decimal('0'),
        'order_count': agg['order_count'] or 0,
        'payment_breakdown': payment_breakdown,
        'legacy_fallback_count': orders_qs.filter(delivery_confirmed_at__isnull=True).count(),
        'orders_qs': orders_qs,
    }


def _pdl_calculation(year, month, product_income):
    """Net Product Income for a month. If the month has already been
    finalized, returns the locked snapshot instead of recomputing — a
    finalized month's figures never silently drift because an expense was
    approved afterwards."""
    period = MonthlyPeriod.objects.filter(year=year, month=month).first()

    if period and period.is_finalized:
        return {
            'period': period,
            'approved_expenses': period.locked_approved_expenses or Decimal('0'),
            'net_product_income': period.locked_net_product_income or Decimal('0'),
            'is_locked': True,
        }

    approved_expenses = Decimal('0')
    if period:
        approved_expenses = period.expenses.filter(is_approved=True).aggregate(
            t=Sum('amount')
        )['t'] or Decimal('0')

    net_product_income = product_income - approved_expenses

    return {
        'period': period,
        'approved_expenses': approved_expenses,
        'net_product_income': net_product_income,
        'is_locked': False,
    }


def _available_report_years():
    years = set(
        Order.objects.filter(status='delivered')
        .annotate(revenue_date=Coalesce('delivery_confirmed_at', 'created_at'))
        .annotate(y=ExtractYear('revenue_date'))
        .values_list('y', flat=True)
        .distinct()
    )
    years.add(timezone.now().year)
    return sorted(years, reverse=True)


def _resolve_selected_period(request):
    now = timezone.now()
    try:
        year = int(request.GET.get('year') or request.POST.get('year') or now.year)
    except (TypeError, ValueError):
        year = now.year
    try:
        month = int(request.GET.get('month') or request.POST.get('month') or now.month)
    except (TypeError, ValueError):
        month = now.month
    if month < 1 or month > 12:
        month = now.month
    return year, month


def _reports_redirect_url(year, month):
    return f"{reverse('dashboard:reports')}?year={year}&month={month}"


@staff_required
def reports(request):
    now = timezone.now()
    available_years = _available_report_years()
    selected_year, selected_month = _resolve_selected_period(request)
    if selected_year not in available_years:
        available_years = sorted(set(available_years + [selected_year]), reverse=True)
    period_label = date(selected_year, selected_month, 1).strftime('%B %Y')

    financials = _financial_summary(selected_year, selected_month)
    pdl = _pdl_calculation(selected_year, selected_month, financials['product_income'])
    monthly_period = pdl['period']
    expenses = monthly_period.expenses.all() if monthly_period else Expense.objects.none()

    gcash_row = next((r for r in financials['payment_breakdown'] if r['payment_method'] == 'gcash'), None)
    cod_row = next((r for r in financials['payment_breakdown'] if r['payment_method'] == 'cod'), None)
    gcash_product_income = gcash_row['product_income'] if gcash_row else Decimal('0')
    cod_product_income = cod_row['product_income'] if cod_row else Decimal('0')

    # ── Secondary "Sales Analytics" section — order activity within the
    # selected month, scoped by created_at (when the order was placed),
    # kept separate from delivery-based revenue recognition above.
    orders_created_qs = Order.objects.filter(
        created_at__year=selected_year, created_at__month=selected_month
    )
    items_qs = OrderItem.objects.filter(order__in=orders_created_qs)
    sales_by_status = orders_created_qs.values('status').annotate(
        count=Count('id'), revenue=Sum('total')
    ).order_by('-count')
    top_products = (items_qs.values('product_name')
                    .annotate(units=Sum('quantity'), revenue=Sum('product_price'))
                    .order_by('-units')[:10])

    # Trend chart is anchored to the selected YEAR (Jan–Dec) rather than a
    # rolling window that could bleed across years, so it never mixes data
    # outside the period the administrator has chosen.
    monthly_trend = (Order.objects.filter(created_at__year=selected_year)
                     .annotate(month=TruncMonth('created_at'))
                     .values('month')
                     .annotate(orders=Count('id'), revenue=Sum('total'))
                     .order_by('month'))

    # ── Monthly History — full-year breakdown for the selected year ──
    period_rows = {p.month: p for p in MonthlyPeriod.objects.filter(year=selected_year)}
    monthly_history = []
    for m in range(1, 13):
        m_fin = _financial_summary(selected_year, m)
        m_pdl = _pdl_calculation(selected_year, m, m_fin['product_income'])
        m_period = period_rows.get(m)
        monthly_history.append({
            'month': m,
            'month_name': calendar.month_name[m],
            'product_income': m_fin['product_income'],
            'shipping_income': m_fin['shipping_income'],
            'order_count': m_fin['order_count'],
            'gcash_income': next((r['product_income'] for r in m_fin['payment_breakdown'] if r['payment_method'] == 'gcash'), Decimal('0')),
            'cod_income': next((r['product_income'] for r in m_fin['payment_breakdown'] if r['payment_method'] == 'cod'), Decimal('0')),
            'approved_expenses': m_pdl['approved_expenses'],
            'net_product_income': m_pdl['net_product_income'],
            'status': m_period.get_status_display() if m_period else 'Open',
            'is_finalized': m_period.is_finalized if m_period else False,
        })

    ctx = {
        'available_years': available_years,
        'months': [(i, calendar.month_name[i]) for i in range(1, 13)],
        'selected_year': selected_year,
        'selected_month': selected_month,
        'period_label': period_label,
        'financials': financials,
        'gcash_product_income': gcash_product_income,
        'cod_product_income': cod_product_income,
        'pdl': pdl,
        'monthly_period': monthly_period,
        'expenses': expenses,
        'sales_by_status': sales_by_status,
        'top_products': top_products,
        'monthly_trend': monthly_trend,
        'monthly_history': monthly_history,
        'expense_categories': Expense.CATEGORY_CHOICES,
    }
    return render(request, 'dashboard/reports.html', ctx)


@staff_required
@require_POST
def reports_expense_add(request):
    year, month = _resolve_selected_period(request)
    period = MonthlyPeriod.get_or_create_for(year, month)
    redirect_url = _reports_redirect_url(year, month)

    if period.is_finalized:
        messages.error(request, f'{period.month_name} {period.year} is finalized. Reopen it before adding expenses.')
        return redirect(redirect_url)

    description = (request.POST.get('description') or '').strip()
    amount_raw = (request.POST.get('amount') or '').strip()
    category = request.POST.get('category') or 'other'

    if not description:
        messages.error(request, 'Enter a description for the expense.')
        return redirect(redirect_url)
    try:
        amount = Decimal(amount_raw)
        if amount <= 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        messages.error(request, 'Enter a valid expense amount greater than zero.')
        return redirect(redirect_url)

    expense = Expense.objects.create(
        period=period, description=description, amount=amount,
        category=category, added_by=request.user,
    )
    log_activity(
        request, action='create',
        description=f'Added expense "{description}" (₱{amount:,.2f}) for {period.month_name} {period.year}',
        resource='Expense', resource_label=description[:255], new_value=f'₱{amount:,.2f}',
    )
    messages.success(request, 'Expense added. It needs admin approval before it affects Net Product Income.')
    return redirect(redirect_url)


@admin_required
@require_POST
def reports_expense_approve(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    year, month = expense.period.year, expense.period.month
    redirect_url = _reports_redirect_url(year, month)

    if expense.period.is_finalized:
        messages.error(request, 'This month is finalized. Reopen it before approving expenses.')
        return redirect(redirect_url)
    if expense.is_approved:
        messages.info(request, 'That expense is already approved.')
        return redirect(redirect_url)

    expense.is_approved = True
    expense.approved_by = request.user
    expense.approved_at = timezone.now()
    expense.save(update_fields=['is_approved', 'approved_by', 'approved_at'])
    log_activity(
        request, action='update',
        description=f'Approved expense "{expense.description}" (₱{expense.amount:,.2f})',
        resource='Expense', resource_label=expense.description[:255],
        previous_value='Pending', new_value='Approved',
    )
    messages.success(request, 'Expense approved.')
    return redirect(redirect_url)


@admin_required
@require_POST
def reports_expense_delete(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    year, month = expense.period.year, expense.period.month
    redirect_url = _reports_redirect_url(year, month)

    if expense.period.is_finalized:
        messages.error(request, 'This month is finalized. Reopen it before deleting expenses.')
        return redirect(redirect_url)

    label = expense.description
    amount = expense.amount
    expense.delete()
    log_activity(
        request, action='delete',
        description=f'Deleted expense "{label}" (₱{amount:,.2f})',
        resource='Expense', resource_label=label[:255], previous_value=f'₱{amount:,.2f}',
    )
    messages.success(request, 'Expense deleted.')
    return redirect(redirect_url)


@admin_required
@require_POST
def reports_finalize_month(request):
    year, month = _resolve_selected_period(request)
    redirect_url = _reports_redirect_url(year, month)
    period = MonthlyPeriod.get_or_create_for(year, month)

    if period.is_finalized:
        messages.info(request, f'{period.month_name} {period.year} is already finalized.')
        return redirect(redirect_url)

    financials = _financial_summary(year, month)
    pdl = _pdl_calculation(year, month, financials['product_income'])

    period.status = MonthlyPeriod.STATUS_FINALIZED
    period.finalized_by = request.user
    period.finalized_at = timezone.now()
    period.locked_product_income = financials['product_income']
    period.locked_shipping_income = financials['shipping_income']
    period.locked_approved_expenses = pdl['approved_expenses']
    period.locked_net_product_income = pdl['net_product_income']
    period.save()

    log_activity(
        request, action='update',
        description=(
            f'Finalized {period.month_name} {period.year}. '
            f'Net Product Income ₱{pdl["net_product_income"]:,.2f}.'
        ),
        resource='MonthlyPeriod', resource_label=f'{period.month_name} {period.year}',
        previous_value='Open', new_value='Finalized',
    )
    messages.success(request, f'{period.month_name} {period.year} has been finalized and locked.')
    return redirect(redirect_url)


@admin_required
@require_POST
def reports_reopen_month(request):
    year, month = _resolve_selected_period(request)
    redirect_url = _reports_redirect_url(year, month)
    period = get_object_or_404(MonthlyPeriod, year=year, month=month)

    if not period.is_finalized:
        messages.info(request, f'{period.month_name} {period.year} is already open.')
        return redirect(redirect_url)

    period.status = MonthlyPeriod.STATUS_OPEN
    period.reopened_by = request.user
    period.reopened_at = timezone.now()
    period.save()

    log_activity(
        request, action='update',
        description=f'Reopened {period.month_name} {period.year} for editing.',
        resource='MonthlyPeriod', resource_label=f'{period.month_name} {period.year}',
        previous_value='Finalized', new_value='Open',
    )
    messages.success(request, f'{period.month_name} {period.year} has been reopened. Its previously locked figures are kept until re-finalized.')
    return redirect(redirect_url)


@admin_required
@throttle(_export_throttle_key, EXPORT_MAX_PER_HOUR)
def reports_export_excel(request):
    """Branded, print-ready Excel export of the Financial Report — always
    for exactly one selected month/year, matching what's on screen."""
    now = timezone.now()
    selected_year, selected_month = _resolve_selected_period(request)
    period_label = date(selected_year, selected_month, 1).strftime('%B %Y')

    financials = _financial_summary(selected_year, selected_month)
    pdl = _pdl_calculation(selected_year, selected_month, financials['product_income'])
    orders_qs = financials['orders_qs'].order_by('delivery_confirmed_at', 'created_at')

    gcash_row = next((r for r in financials['payment_breakdown'] if r['payment_method'] == 'gcash'), None)
    cod_row = next((r for r in financials['payment_breakdown'] if r['payment_method'] == 'cod'), None)
    gcash_total = gcash_row['total'] if gcash_row else Decimal('0')
    cod_total = cod_row['total'] if cod_row else Decimal('0')
    gcash_product = gcash_row['product_income'] if gcash_row else Decimal('0')
    cod_product = cod_row['product_income'] if cod_row else Decimal('0')

    BLACK = '000000'
    DARK_GRAY = '333333'
    MID_GRAY = '666666'
    LIGHT_GRAY = 'F2F2F2'
    HEADER_GRAY = 'D9D9D9'
    WHITE = 'FFFFFF'

    title_font = Font(name='Calibri', size=18, bold=True, color=BLACK)
    subtitle_font = Font(name='Calibri', size=10, italic=True, color=MID_GRAY)
    section_font = Font(name='Calibri', size=12, bold=True, color=BLACK)
    header_font = Font(name='Calibri', size=10, bold=True, color=BLACK)
    label_font = Font(name='Calibri', size=10, color=MID_GRAY)
    value_font = Font(name='Calibri', size=14, bold=True, color=BLACK)
    body_font = Font(name='Calibri', size=10, color=DARK_GRAY)
    total_font = Font(name='Calibri', size=10, bold=True, color=BLACK)

    section_fill = PatternFill('solid', fgColor=HEADER_GRAY)
    header_fill = PatternFill('solid', fgColor=HEADER_GRAY)
    zebra_fill = PatternFill('solid', fgColor=LIGHT_GRAY)
    white_fill = PatternFill('solid', fgColor=WHITE)

    thin = Side(style='thin', color='CCCCCC')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal='center', vertical='center')
    left = Alignment(horizontal='left', vertical='center')

    wb = Workbook()

    # ── Sheet 1: Financial Summary ──
    ws = wb.active
    ws.title = 'Financial Summary'
    ws.sheet_view.showGridLines = False
    for i, w in enumerate([32, 20, 20, 20, 20], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    row = 1
    ws.merge_cells(f'A{row}:E{row}')
    c = ws[f'A{row}']; c.value = 'LIKHALAYA'; c.font = title_font; c.alignment = center
    row += 1
    ws.merge_cells(f'A{row}:E{row}')
    c = ws[f'A{row}']; c.value = 'PDL Market — Monthly Financial Report'
    c.font = Font(name='Calibri', size=11, bold=True, color=DARK_GRAY); c.alignment = center
    row += 1
    ws.merge_cells(f'A{row}:E{row}')
    c = ws[f'A{row}']; c.value = f'Period: {period_label}'
    c.font = Font(name='Calibri', size=10, bold=True, color=BLACK); c.alignment = center
    row += 1
    ws.merge_cells(f'A{row}:E{row}')
    c = ws[f'A{row}']; c.value = f'Generated {now.strftime("%B %d, %Y at %I:%M %p")}'
    c.font = subtitle_font; c.alignment = center
    row += 2

    def section_header(title):
        nonlocal row
        ws.merge_cells(f'A{row}:E{row}')
        cell = ws[f'A{row}']
        cell.value = title
        cell.font = section_font
        cell.alignment = center
        for col in ['A', 'B', 'C', 'D', 'E']:
            ws[f'{col}{row}'].fill = section_fill
        ws.row_dimensions[row].height = 20
        row += 1

    def label_value_row(label, value, bold=False):
        nonlocal row
        ws.merge_cells(f'A{row}:C{row}')
        lc = ws[f'A{row}']; lc.value = label; lc.font = total_font if bold else body_font
        lc.alignment = left; lc.border = border
        ws.merge_cells(f'D{row}:E{row}')
        vc = ws[f'D{row}']; vc.value = value; vc.font = total_font if bold else body_font
        vc.alignment = center; vc.border = border
        for col in ['A', 'B', 'C']:
            ws[f'{col}{row}'].border = border
        row += 1

    section_header('Monthly Financial Summary')
    label_value_row('Product Income', f"₱{financials['product_income']:,.2f}")
    label_value_row('Shipping Fee Income', f"₱{financials['shipping_income']:,.2f}")
    label_value_row('Total Order Value (Product + Shipping)', f"₱{financials['gross_total']:,.2f}", bold=True)
    row += 1
    label_value_row('GCash Income (Product + Shipping)', f"₱{gcash_total:,.2f}")
    label_value_row('Cash on Delivery Income (Product + Shipping)', f"₱{cod_total:,.2f}")
    row += 1
    label_value_row('Approved Expenses', f"₱{pdl['approved_expenses']:,.2f}")
    label_value_row('Net Product Income', f"₱{pdl['net_product_income']:,.2f}", bold=True)
    row += 1
    period_status = pdl['period'].get_status_display() if pdl['period'] else 'Open'
    label_value_row('Month Status', period_status)
    if pdl['is_locked']:
        row += 1
        ws.merge_cells(f'A{row}:E{row}')
        note = ws[f'A{row}']
        note.value = 'This month is finalized. Figures above are the locked snapshot recorded at finalization.'
        note.font = subtitle_font
        note.alignment = center
        row += 1
    row += 1
    ws.merge_cells(f'A{row}:E{row}')
    note = ws[f'A{row}']
    note.value = 'PDL sharing is decided and distributed by the coordinator outside this system.'
    note.font = subtitle_font
    note.alignment = center
    row += 2

    # Income by Payment Method
    section_header('Income by Payment Method')
    headers = ['Payment Method', 'Product Income', 'Shipping Fees', 'Total', 'Orders']
    for h, col in zip(headers, ['A', 'B', 'C', 'D', 'E']):
        cell = ws[f'{col}{row}']
        cell.value = h; cell.font = header_font; cell.fill = header_fill
        cell.alignment = center; cell.border = border
    row += 1
    payment_display = dict(Order.PAYMENT_CHOICES)
    for i, r in enumerate(financials['payment_breakdown']):
        fill = zebra_fill if i % 2 else white_fill
        values = [
            payment_display.get(r['payment_method'], r['payment_method']),
            f"₱{r['product_income'] or 0:,.2f}",
            f"₱{r['shipping_income'] or 0:,.2f}",
            f"₱{r['total'] or 0:,.2f}",
            r['orders'],
        ]
        for v, col in zip(values, ['A', 'B', 'C', 'D', 'E']):
            cell = ws[f'{col}{row}']
            cell.value = v; cell.font = body_font; cell.fill = fill
            cell.alignment = center; cell.border = border
        row += 1
    totals = ['TOTAL', f"₱{financials['product_income']:,.2f}", f"₱{financials['shipping_income']:,.2f}",
              f"₱{financials['gross_total']:,.2f}", financials['order_count']]
    for v, col in zip(totals, ['A', 'B', 'C', 'D', 'E']):
        cell = ws[f'{col}{row}']
        cell.value = v; cell.font = total_font; cell.fill = header_fill
        cell.alignment = center; cell.border = border
    row += 3

    ws.merge_cells(f'A{row}:E{row}')
    footer = ws[f'A{row}']
    footer.value = 'Likhalaya PDL Market — Confidential internal financial report'
    footer.font = Font(name='Calibri', size=8, italic=True, color='AAAAAA')
    footer.alignment = center

    ws.print_area = f'A1:E{row}'
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5

    # ── Sheet 2: Orders ──
    ws2 = wb.create_sheet('Orders')
    ws2.sheet_view.showGridLines = False
    headers = ['Order ID', 'Delivery Date', 'Payment Method', 'Product Income', 'Shipping Fee', 'Order Total', 'Status']
    widths = [14, 18, 16, 16, 14, 14, 14]
    for i, w in enumerate(widths, start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    for col_idx, h in enumerate(headers, start=1):
        cell = ws2.cell(row=1, column=col_idx)
        cell.value = h; cell.font = header_font; cell.fill = header_fill
        cell.alignment = center; cell.border = border
    status_display = dict(Order.STATUS_CHOICES)
    r_idx = 2
    for i, o in enumerate(orders_qs):
        fill = zebra_fill if i % 2 else white_fill
        delivery_date = o.delivery_confirmed_at or o.created_at
        row_values = [
            o.order_number,
            delivery_date.strftime('%Y-%m-%d %I:%M %p') if delivery_date else '—',
            payment_display.get(o.payment_method, o.payment_method),
            f"₱{o.subtotal:,.2f}",
            f"₱{o.shipping_fee:,.2f}",
            f"₱{o.total:,.2f}",
            status_display.get(o.status, o.status),
        ]
        for col_idx, v in enumerate(row_values, start=1):
            cell = ws2.cell(row=r_idx, column=col_idx)
            cell.value = v; cell.font = body_font; cell.fill = fill
            cell.alignment = center; cell.border = border
        r_idx += 1
    ws2.print_area = f'A1:G{max(r_idx - 1, 1)}'
    ws2.page_setup.orientation = 'landscape'
    ws2.page_setup.fitToWidth = 1
    ws2.sheet_properties.pageSetUpPr.fitToPage = True

    # ── Sheet 3: PDL Share ── (calculation only — no individual payout tracking)
    ws3 = wb.create_sheet('PDL Share')
    ws3.sheet_view.showGridLines = False
    for i, w in enumerate([28, 22], start=1):
        ws3.column_dimensions[get_column_letter(i)].width = w
    row = 1
    ws3.merge_cells(f'A{row}:B{row}')
    c = ws3[f'A{row}']; c.value = f'PDL Share Calculation — {period_label}'
    c.font = section_font; c.alignment = center; c.fill = section_fill
    row += 2
    pdl_rows = [
        ('Product Income', f"₱{financials['product_income']:,.2f}"),
        ('Approved Expenses', f"₱{pdl['approved_expenses']:,.2f}"),
        ('Net Product Income', f"₱{pdl['net_product_income']:,.2f}"),
        ('PDL Share %', pdl_pct_display),
        ('PDL Share Amount', pdl_amt_display),
        ('Month Status', period_status),
    ]
    for label, value in pdl_rows:
        ws3[f'A{row}'].value = label; ws3[f'A{row}'].font = body_font
        ws3[f'A{row}'].border = border; ws3[f'A{row}'].alignment = left
        ws3[f'B{row}'].value = value; ws3[f'B{row}'].font = total_font
        ws3[f'B{row}'].border = border; ws3[f'B{row}'].alignment = center
        row += 1
    row += 1
    ws3.merge_cells(f'A{row}:B{row}')
    note = ws3[f'A{row}']
    note.value = 'Actual PDL distribution is handled manually by the client and is outside this system.'
    note.font = subtitle_font
    note.alignment = center

    buffer_bytes = _xlsx_bytes(wb)
    response = HttpResponse(
        buffer_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    filename = f'Likhalaya_Financial_Report_{selected_year}_{selected_month:02d}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ─── Customer Dashboard ─────────────────────────────────────────────────────────
@login_required
def customer_dashboard(request):
    orders = Order.objects.filter(user=request.user).prefetch_related('items').order_by('-created_at')
    stats = {
        'total_orders': orders.count(),
        'pending': orders.filter(status='pending').count(),
        'delivered': orders.filter(status='delivered').count(),
        'total_spent': orders.filter(status='delivered').aggregate(t=Sum('total'))['t'] or 0,
    }
    recent_orders = orders[:5]
    return render(request, 'dashboard/customer/home.html', {
        'stats': stats,
        'recent_orders': recent_orders,
    })


# ─── Livelihood Videos ──────────────────────────────────────────────────────────
@staff_required
def video_list(request):
    videos = LivelihoodVideo.objects.all().order_by('order', '-created_at')
    return render(request, 'dashboard/videos/list.html', {'videos': videos})


@staff_required
def video_create(request):
    from store.forms import LivelihoodVideoForm
    if request.method == 'POST':
        form = LivelihoodVideoForm(request.POST, request.FILES)
        if form.is_valid():
            video = form.save()
            log_activity(request, 'create', f'Added livelihood video "{video.title}"',
                         resource='LivelihoodVideo', resource_label=video.title)
            messages.success(request, 'Video added.')
            return redirect('dashboard:video_list')
        else:
            for error in form.errors.get('show_on_home', []):
                messages.error(request, error)
    else:
        form = LivelihoodVideoForm()
    home_count = LivelihoodVideo.objects.filter(show_on_home=True).count()
    return render(request, 'dashboard/videos/form.html', {
        'form': form, 'title': 'Add Video', 'home_count': home_count,
    })


@admin_required
def video_edit(request, pk):
    from store.forms import LivelihoodVideoForm
    video = get_object_or_404(LivelihoodVideo, pk=pk)
    if request.method == 'POST':
        form = LivelihoodVideoForm(request.POST, request.FILES, instance=video)
        if form.is_valid():
            form.save()
            log_activity(request, 'update', f'Updated livelihood video "{video.title}"',
                         resource='LivelihoodVideo', resource_label=video.title)
            messages.success(request, 'Video updated.')
            return redirect('dashboard:video_list')
        else:
            for error in form.errors.get('show_on_home', []):
                messages.error(request, error)
    else:
        form = LivelihoodVideoForm(instance=video)
    home_count = LivelihoodVideo.objects.filter(show_on_home=True).exclude(pk=video.pk).count()
    return render(request, 'dashboard/videos/form.html', {
        'form': form, 'title': 'Edit Video', 'video': video, 'home_count': home_count,
    })


@admin_required
def video_delete(request, pk):
    video = get_object_or_404(LivelihoodVideo, pk=pk)
    if request.method == 'POST':
        title = video.title
        video.archive(by_user=request.user)
        log_activity(request, 'delete', f'Archived livelihood video "{title}"',
                     resource='LivelihoodVideo', resource_label=title)
        messages.success(request, f'Video "{title}" moved to the Archive.')
        return redirect('dashboard:video_list')
    return render(request, 'dashboard/videos/confirm_delete.html', {'video': video})


@admin_required
def video_restore(request, pk):
    video = get_object_or_404(LivelihoodVideo.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        video.restore()
        log_activity(request, 'restore', f'Restored livelihood video "{video.title}"',
                     resource='LivelihoodVideo', resource_label=video.title)
        messages.success(request, f'Video "{video.title}" restored.')
    return redirect('dashboard:archive')


@admin_required
def video_delete_permanent(request, pk):
    video = get_object_or_404(LivelihoodVideo.all_objects, pk=pk, is_deleted=True)
    if request.method == 'POST':
        title = video.title
        log_activity(request, 'delete', f'Permanently deleted livelihood video "{title}"',
                     resource='LivelihoodVideo', resource_label=title)
        video.delete()
        messages.success(request, f'Video "{title}" permanently deleted.')
    return redirect('dashboard:archive')

# ─── GCash QR Code Management ──────────────────────────────────────────────
QR_MIN_SIZE = 5 * 1024        # 5 KB
QR_MAX_SIZE = 2 * 1024 * 1024  # 2 MB
QR_ALLOWED_EXTS = ('.png', '.jpg', '.jpeg')


def _qr_validate_image(f):
    """Returns an error string, or None if the uploaded file is acceptable."""
    if not f:
        return 'Please choose a QR code image to upload.'
    name = f.name.lower()
    if not name.endswith(QR_ALLOWED_EXTS):
        return 'Only PNG, JPG, or JPEG image files are allowed.'
    if f.size < QR_MIN_SIZE:
        return 'That image is too small to be a real QR code. Please upload a genuine QR code image.'
    if f.size > QR_MAX_SIZE:
        return 'That image is too large (must be under 2 MB).'
    return None


@staff_required
def gcash_qr_manage(request):
    """Main Staff page: read-only view of the GCash QR code exactly as
    customers see it at checkout ("Pay with GCash"). Staff can look, but
    only an Administrator can upload, replace, or remove it — that's done
    from the separate Admin QR page (gcash_qr_admin)."""
    pending = GCashQRCode.get_pending_confirm()
    active = GCashQRCode.get_active()
    latest_request = None
    if active:
        latest_request = active.removal_requests.order_by('-created_at').first()

    return render(request, 'dashboard/gcash_qr/manage.html', {
        'pending': pending,
        'active': active,
        'latest_request': latest_request,
        'can_upload': GCashQRCode.can_staff_upload_new(),
        'removal_reasons': GCashQRRemovalRequest.REASON_CHOICES,
    })


@admin_required
@require_POST
def gcash_qr_upload(request):
    """Admin-only: selects a QR image. This does NOT activate it yet — it's
    saved as a pending preview that must be explicitly confirmed."""
    if not GCashQRCode.can_staff_upload_new():
        messages.error(request, 'A GCash QR code is already active or awaiting action. It must be cleared before uploading a new one.')
        return redirect('dashboard:gcash_qr_manage')

    f = request.FILES.get('image')
    error = _qr_validate_image(f)
    if error:
        messages.error(request, error)
        return redirect('dashboard:gcash_qr_manage')

    qr = GCashQRCode.objects.create(
        image=f, status=GCashQRCode.STATUS_PENDING_CONFIRM, uploaded_by=request.user,
    )
    log_activity(request, 'create', 'Uploaded a GCash QR code for preview (not yet activated)',
                 resource='GCashQRCode', resource_label=f'QR #{qr.pk}')
    messages.success(request, 'QR code uploaded. Review the preview carefully before confirming.')
    return redirect('dashboard:gcash_qr_manage')


@admin_required
@require_POST
def gcash_qr_cancel_preview(request, pk):
    """Discard an unconfirmed preview and return to the upload screen."""
    qr = get_object_or_404(GCashQRCode, pk=pk, status=GCashQRCode.STATUS_PENDING_CONFIRM)
    qr.delete()
    messages.info(request, 'Upload cancelled.')
    return redirect('dashboard:gcash_qr_manage')


@admin_required
@require_POST
def gcash_qr_confirm(request, pk):
    """Locks in the previewed QR code as the active GCash QR code. Only an
    Administrator can do this — once locked it can only be changed by an
    Administrator again."""
    qr = get_object_or_404(GCashQRCode, pk=pk, status=GCashQRCode.STATUS_PENDING_CONFIRM)
    qr.status = GCashQRCode.STATUS_ACTIVE_LOCKED
    qr.confirmed_at = timezone.now()
    qr.save(update_fields=['status', 'confirmed_at'])
    log_activity(request, 'status_change', 'Confirmed and activated a GCash QR code (now locked)',
                 resource='GCashQRCode', resource_label=f'QR #{qr.pk}',
                 previous_value='Pending Staff Confirmation', new_value='Active & Locked')
    messages.success(request, 'GCash QR code is now Active & Locked.')
    return redirect('dashboard:gcash_qr_manage')


@staff_required
def gcash_qr_request_removal(request, pk):
    """Staff-facing form to request that an Admin remove/replace the
    currently locked QR code."""
    qr = get_object_or_404(GCashQRCode, pk=pk)
    if qr.status not in (GCashQRCode.STATUS_ACTIVE_LOCKED,):
        messages.error(request, 'A removal request can only be submitted for an active, locked QR code.')
        return redirect('dashboard:gcash_qr_manage')

    if request.method == 'POST':
        reason = request.POST.get('reason', GCashQRRemovalRequest.REASON_OTHER)
        explanation = request.POST.get('explanation', '').strip()
        valid_reasons = dict(GCashQRRemovalRequest.REASON_CHOICES)
        if reason not in valid_reasons:
            reason = GCashQRRemovalRequest.REASON_OTHER
        if reason == GCashQRRemovalRequest.REASON_OTHER and not explanation:
            messages.error(request, 'Please provide an explanation for "Other reason".')
            return redirect('dashboard:gcash_qr_request_removal', pk=qr.pk)

        req = GCashQRRemovalRequest.objects.create(
            qr_code=qr, requested_by=request.user, reason=reason, explanation=explanation,
        )
        qr.status = GCashQRCode.STATUS_REMOVAL_PENDING
        qr.save(update_fields=['status'])
        log_activity(request, 'other', f'Requested removal of GCash QR code ({req.get_reason_display()})',
                     resource='GCashQRCode', resource_label=f'QR #{qr.pk}',
                     previous_value='Active & Locked', new_value='Removal Request Pending')
        messages.success(request, 'Your removal request has been submitted to the Administrator.')
        return redirect('dashboard:gcash_qr_manage')

    return render(request, 'dashboard/gcash_qr/request_removal.html', {
        'qr': qr,
        'removal_reasons': GCashQRRemovalRequest.REASON_CHOICES,
    })


# ── Admin authority ──
@admin_required
def gcash_qr_admin(request):
    """Admin overview: current QR code, its full history (paginated, 5 per
    page), and any pending or past Staff removal/replacement requests."""
    active = GCashQRCode.get_active()
    pending = GCashQRCode.get_pending_confirm()

    history_qs = GCashQRCode.objects.all().order_by('-created_at')
    paginator = Paginator(history_qs, 5)
    page_number = request.GET.get('history_page')
    history = paginator.get_page(page_number)

    requests_qs = GCashQRRemovalRequest.objects.select_related('qr_code', 'requested_by', 'decided_by').order_by('-created_at')[:25]

    return render(request, 'dashboard/gcash_qr/admin.html', {
        'active': active,
        'pending': pending,
        'history': history,
        'requests': requests_qs,
    })


@admin_required
@require_POST
def gcash_qr_request_approve(request, pk):
    """Admin approves a Staff removal request: the old QR is deactivated
    and Staff regain the ability to upload a replacement."""
    req = get_object_or_404(GCashQRRemovalRequest, pk=pk, status=GCashQRRemovalRequest.STATUS_PENDING)
    qr = req.qr_code
    decision_reason = request.POST.get('decision_reason', '').strip()

    req.status = GCashQRRemovalRequest.STATUS_APPROVED
    req.decided_by = request.user
    req.decision_reason = decision_reason
    req.decided_at = timezone.now()
    req.save(update_fields=['status', 'decided_by', 'decision_reason', 'decided_at'])

    qr.status = GCashQRCode.STATUS_INACTIVE
    qr.deactivated_at = timezone.now()
    qr.save(update_fields=['status', 'deactivated_at'])

    log_activity(request, 'status_change', 'Approved GCash QR removal request — QR deactivated, Staff can upload a replacement',
                 resource='GCashQRCode', resource_label=f'QR #{qr.pk}',
                 previous_value='Removal Request Pending', new_value='Removal Approved / Inactive')
    messages.success(request, 'Removal request approved. The QR code has been deactivated; Staff may now upload a new one.')
    return redirect('dashboard:gcash_qr_admin')


@admin_required
@require_POST
def gcash_qr_request_reject(request, pk):
    """Admin rejects a Staff removal request: the existing QR stays active
    and locked."""
    req = get_object_or_404(GCashQRRemovalRequest, pk=pk, status=GCashQRRemovalRequest.STATUS_PENDING)
    qr = req.qr_code
    decision_reason = request.POST.get('decision_reason', '').strip()

    req.status = GCashQRRemovalRequest.STATUS_REJECTED
    req.decided_by = request.user
    req.decision_reason = decision_reason
    req.decided_at = timezone.now()
    req.save(update_fields=['status', 'decided_by', 'decision_reason', 'decided_at'])

    qr.status = GCashQRCode.STATUS_REMOVAL_REJECTED
    qr.save(update_fields=['status'])

    log_activity(request, 'status_change', 'Rejected GCash QR removal request — QR remains active and locked',
                 resource='GCashQRCode', resource_label=f'QR #{qr.pk}',
                 previous_value='Removal Request Pending', new_value='Removal Rejected')
    messages.success(request, 'Removal request rejected. The current QR code remains active and locked.')
    return redirect('dashboard:gcash_qr_admin')


@admin_required
@require_POST
def gcash_qr_admin_upload(request):
    """Admin override: directly upload the first/replacement QR code when
    there's no active one yet (no Staff confirmation step needed)."""
    f = request.FILES.get('image')
    error = _qr_validate_image(f)
    if error:
        messages.error(request, error)
        return redirect('dashboard:gcash_qr_admin')

    new_qr = GCashQRCode.objects.create(
        image=f, status=GCashQRCode.STATUS_ACTIVE_LOCKED, uploaded_by=request.user,
        confirmed_at=timezone.now(),
        account_name=request.POST.get('account_name', '').strip(),
        account_number=request.POST.get('account_number', '').strip(),
    )
    log_activity(request, 'create', 'Uploaded GCash QR code directly (Admin)',
                 resource='GCashQRCode', resource_label=f'QR #{new_qr.pk}')
    messages.success(request, 'GCash QR code uploaded and is now active.')
    return redirect('dashboard:gcash_qr_admin')


@admin_required
@require_POST
def gcash_qr_admin_update_details(request, pk):
    """Admin-only: update the account name/number shown alongside the
    currently active QR code, without touching the QR image itself."""
    qr = get_object_or_404(GCashQRCode, pk=pk)
    qr.account_name = request.POST.get('account_name', '').strip()
    qr.account_number = request.POST.get('account_number', '').strip()
    qr.save(update_fields=['account_name', 'account_number'])
    log_activity(request, 'update', 'Updated GCash account name/number shown at checkout',
                 resource='GCashQRCode', resource_label=f'QR #{qr.pk}')
    messages.success(request, 'Account details updated.')
    return redirect('dashboard:gcash_qr_admin')


@admin_required
@require_POST
def gcash_qr_admin_replace(request, pk):
    """Admin override: directly replace the active QR code, bypassing the
    Staff confirm/removal-request workflow entirely."""
    qr = get_object_or_404(GCashQRCode, pk=pk)
    f = request.FILES.get('image')
    error = _qr_validate_image(f)
    if error:
        messages.error(request, error)
        return redirect('dashboard:gcash_qr_admin')

    qr.status = GCashQRCode.STATUS_INACTIVE
    qr.deactivated_at = timezone.now()
    qr.save(update_fields=['status', 'deactivated_at'])

    new_qr = GCashQRCode.objects.create(
        image=f, status=GCashQRCode.STATUS_ACTIVE_LOCKED, uploaded_by=request.user,
        confirmed_at=timezone.now(),
        account_name=request.POST.get('account_name', '').strip(),
        account_number=request.POST.get('account_number', '').strip(),
    )
    log_activity(request, 'update', f'Replaced GCash QR code directly (Admin override), old QR #{qr.pk} deactivated',
                 resource='GCashQRCode', resource_label=f'QR #{new_qr.pk}')
    messages.success(request, 'GCash QR code replaced.')
    return redirect('dashboard:gcash_qr_admin')


@admin_required
@require_POST
def gcash_qr_admin_remove(request, pk):
    """Admin override: deactivate the active QR code directly, with no
    replacement uploaded yet. Staff can then upload a new one."""
    qr = get_object_or_404(GCashQRCode, pk=pk)
    qr.status = GCashQRCode.STATUS_INACTIVE
    qr.deactivated_at = timezone.now()
    qr.save(update_fields=['status', 'deactivated_at'])
    log_activity(request, 'delete', 'Removed active GCash QR code directly (Admin override)',
                 resource='GCashQRCode', resource_label=f'QR #{qr.pk}',
                 previous_value='Active & Locked', new_value='Inactive')
    messages.success(request, 'GCash QR code removed. Staff may now upload a new one.')
    return redirect('dashboard:gcash_qr_admin')