"""Delivery-courier endpoints for the mobile app ("Deliveries").

Mirrors dashboard.views.courier_order_list / courier_order_detail:
  * a courier (or a staff member acting as one) only sees orders the admin
    assigned to them; an admin sees every order that needs a courier action
  * Confirm Pickup needs a proof photo and moves Confirmed -> Shipped
  * Confirm Delivery needs a proof photo and moves Shipped -> Delivered
The customer gets the same in-app notifications as on the website.
"""
import requests
from django.core.files.storage import default_storage
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.activity import log_activity
from orders.models import Order, OrderStatusError, Notification
from orders.validators import validate_payment_proof

from .serializers import OrderSerializer


class IsCourierOrAdmin(BasePermission):
    """Same rule as the website's @courier_required."""
    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_courier_user() or u.is_admin_user()))


def _orders_for(user):
    qs = Order.objects.select_related('assigned_courier', 'user').prefetch_related('items')
    if user.is_courier_user():
        # Staff/couriers only ever see their own assignments (admins are
        # also "staff" but get everything below).
        if not user.is_admin_user():
            qs = qs.filter(assigned_courier=user)
    return qs


class CourierOrderListView(APIView):
    """GET /api/courier/orders/?scope=active|done
    active (default): Confirmed (ready for pickup) and Shipped (on the way)
    done: recently Delivered orders, newest first."""
    permission_classes = [IsCourierOrAdmin]

    def get(self, request):
        qs = _orders_for(request.user)
        if request.query_params.get('scope') == 'done':
            qs = qs.filter(status='delivered').order_by('-delivery_confirmed_at', '-updated_at')[:50]
        else:
            qs = qs.filter(status__in=['confirmed', 'shipped']).order_by('-created_at')
        return Response(OrderSerializer(qs, many=True, context={'request': request}).data)


class _CourierConfirmBase(APIView):
    permission_classes = [IsCourierOrAdmin]
    method_name = ''       # Order method to call
    file_field = 'proof'
    note = ''              # notification text, {n} = order number

    def post(self, request, pk):
        order = _orders_for(request.user).filter(pk=pk).first()
        if order is None:
            return Response({'detail': 'This order is not assigned to you.'},
                            status=status.HTTP_404_NOT_FOUND)
        proof = request.FILES.get(self.file_field)
        if not proof:
            return Response({'detail': 'A proof photo is required.'}, status=400)
        error = validate_payment_proof(proof)
        if error:
            return Response({'detail': error}, status=400)

        old_status = order.status
        try:
            getattr(order, self.method_name)(proof)
        except OrderStatusError as e:
            return Response({'detail': str(e)}, status=400)

        log_activity(
            request, 'status_change',
            f'Order {order.order_number} status: {old_status} → {order.status}',
            resource='Order', resource_label=order.order_number,
            previous_value=old_status, new_value=order.status,
        )
        if order.user:
            Notification.objects.create(
                user=order.user, order=order,
                message=self.note.format(n=order.order_number))
        return Response(OrderSerializer(order, context={'request': request}).data)


class CourierConfirmPickupView(_CourierConfirmBase):
    """POST /api/courier/orders/<id>/confirm-pickup/  (multipart: proof)"""
    method_name = 'confirm_pickup'
    note = 'Good news! Your order {n} has been shipped and is on its way.'


class CourierConfirmDeliveryView(_CourierConfirmBase):
    """POST /api/courier/orders/<id>/confirm-delivery/  (multipart: proof)"""
    method_name = 'confirm_delivery'
    note = 'Your order {n} has been delivered. Enjoy!'


class CourierProofImageView(APIView):
    """GET /api/courier/orders/<id>/proof/<pickup|delivery>/ -> the proof photo.

    Proof photos are private (the website serves them behind a session
    login), so the app fetches them here with its normal login token. Same
    access rule as the rest of this file: the assigned courier, or an admin.
    """
    permission_classes = [IsCourierOrAdmin]

    def get(self, request, pk, kind):
        order = _orders_for(request.user).filter(pk=pk).first()
        if order is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        image = {'pickup': order.pickup_proof, 'delivery': order.delivery_proof}.get(kind)
        if not image:
            return Response({'detail': 'No proof photo yet.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            upstream = requests.get(default_storage.signed_url(image.name), timeout=15)
        except requests.RequestException:
            return Response({'detail': 'Could not load the photo.'}, status=status.HTTP_502_BAD_GATEWAY)
        if upstream.status_code != 200:
            return Response({'detail': 'Could not load the photo.'}, status=status.HTTP_502_BAD_GATEWAY)
        response = HttpResponse(upstream.content,
                                content_type=upstream.headers.get('Content-Type', 'image/jpeg'))
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
