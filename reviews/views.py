from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from likhalaya_project.rate_limit import throttle
from store.models import Product

from .forms import ReviewForm
from .models import Review, public_name_for, user_has_purchased


def _review_throttle_key(request):
    return f'review_submit:{request.user.pk}'


def _back_to_product(product):
    return redirect(f"{product.get_absolute_url()}#reviews")


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

    rating = form.cleaned_data['rating']
    comment = form.cleaned_data['comment']
    name = public_name_for(request.user)

    existing = Review.objects.filter(product=product, user=request.user).first()
    if existing:
        existing.rating = rating
        existing.comment = comment
        existing.reviewer_name = name
        existing.is_verified_purchase = (
            existing.is_verified_purchase or user_has_purchased(request.user, product)
        )
        existing.save()
        messages.success(request, 'Your review was updated.')
        return _back_to_product(product)

    try:
        with transaction.atomic():
            Review.objects.create(
                product=product,
                user=request.user,
                reviewer_name=name,
                rating=rating,
                comment=comment,
                is_verified_purchase=user_has_purchased(request.user, product),
            )
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