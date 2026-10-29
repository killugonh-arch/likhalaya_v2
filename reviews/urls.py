from django.urls import path
from . import views, dashboard_views

app_name = 'reviews'

urlpatterns = [
    # Storefront (customers)
    path('reviews/submit/<slug:slug>/', views.submit_review, name='submit'),
    path('reviews/<int:pk>/delete-mine/', views.delete_my_review, name='delete_mine'),

    # Dashboard (staff / admin)
    path('dashboard/reviews/', dashboard_views.review_list, name='dashboard_list'),
    path('dashboard/reviews/<int:pk>/toggle/', dashboard_views.review_toggle_visible, name='dashboard_toggle'),
    path('dashboard/reviews/<int:pk>/reply/', dashboard_views.review_reply, name='dashboard_reply'),
    path('dashboard/reviews/<int:pk>/delete/', dashboard_views.review_delete, name='dashboard_delete'),
    path('dashboard/reviews/<int:pk>/restore/', dashboard_views.review_restore, name='dashboard_restore'),
    path('dashboard/reviews/<int:pk>/delete-permanent/', dashboard_views.review_delete_permanent, name='dashboard_delete_permanent'),
]