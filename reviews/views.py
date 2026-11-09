from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from likhalaya_project.image_validation import sanitize_image
from likhalaya_project.rate_limit import throttle
from store.models import Product

from .forms import ReviewForm
from .models import Review, ReviewMedia, public_name_for, user_has_purchased

MAX_IMAGES = 3
MAX_IMAGE_MB = 5


def _review_throttle_key(request):
    return f'review_submit:{request.user.pk}'


def _back_to_product(product):
    return redirect(f"{product.get_absolute_url()}#reviews")


def _clean_images(request):
    """Validate uploaded files from the 'media' input.
    Returns (images, error_message_or_None)."""
    images = []
    for f in request.FILES.getlist('media'):
        error = sanitize_image(f, max_bytes=MAX_IMAGE_MB * 1024 * 1024)
        if error:
            return [], error
        images.append(f)
    return images, None


def _delete_media(m):
    if m.image:
        m.image.delete(save=False)
    m.delete()


def _add_images(review, images):
    for f in images:
        ReviewMedia.objects.create(review=review, image=f)


@login_required
@require_POST
@throttle(_review_throttle_key, 30)
def submit_review(request, slug):
    """Create the customer's review for a product, or update it if they
    already left one (one review per customer per product)."""
    product = get_object_or_404(Product, slug=slug, is_active=True)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        for errs in form.errors.values():
            for e in errs:
                messages.error(request, e)
        return _back_to_product(product)

    new_images, upload_error = _clean_images(request)
    if upload_error:
        messages.error(request, upload_error)
        return _back_to_product(product)

    rating = form.cleaned_data['rating']
    comment = form.cleaned_data['comment']
    name = public_name_for(request.user)

    existing = Review.objects.filter(product=product, user=request.user).first()
    # Only customers with a delivered order for this product can post a new review.
    if not existing and not user_has_purchased(request.user, product):
        messages.error(request, 'Only customers who received this product can review it.')
        return _back_to_product(product)

    if existing:
        # Work out what is kept after the customer's removals.
        remove_ids = {int(x) for x in request.POST.getlist('remove_media') if x.isdigit()}
        remove_legacy = request.POST.get('remove_legacy') == '1'
        current_media = list(existing.media.all())
        kept = sum(1 for m in current_media if m.pk not in remove_ids)
        if existing.image and not remove_legacy:
            kept += 1
        if kept + len(new_images) > MAX_IMAGES:
            messages.error(request, f'You can have up to {MAX_IMAGES} photos on a review.')
            return _back_to_product(product)

        with transaction.atomic():
            existing.rating = rating
            if comment:
                existing.comment = comment
            existing.reviewer_name = name
            existing.is_verified_purchase = (
                existing.is_verified_purchase or user_has_purchased(request.user, product)
            )
            if remove_legacy and existing.image:
                existing.image.delete(save=False)
                existing.image = None
            existing.save()
            for m in current_media:
                if m.pk in remove_ids:
                    _delete_media(m)
            _add_images(existing, new_images)
        messages.success(request, 'Your review was updated.')
        return _back_to_product(product)

    if len(new_images) > MAX_IMAGES:
        messages.error(request, f'You can add up to {MAX_IMAGES} photos.')
        return _back_to_product(product)

    try:
        with transaction.atomic():
            review = Review.objects.create(
                product=product,
                user=request.user,
                reviewer_name=name,
                rating=rating,
                comment=comment,
                is_verified_purchase=user_has_purchased(request.user, product),
            )
            _add_images(review, new_images)
    except IntegrityError:
        # Double-click / two tabs: the other request already created it.
        messages.info(request, 'You already reviewed this product.')
        return _back_to_product(product)

    messages.success(request, 'Thanks! Your review has been posted.')
    return _back_to_product(product)


@login_required
@require_POST
def delete_my_review(request, pk):
    review = get_object_or_404(Review, pk=pk, user=request.user)
    product = review.product
    review.delete()
    messages.success(request, 'Your review was deleted.')
    return _back_to_product(product)