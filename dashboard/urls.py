from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard_home, name='home'),
    # Orders
    path('orders/', views.order_list, name='order_list'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/start-processing/', views.order_start_processing, name='order_start_processing'),
    path('orders/<int:pk>/mark-ready/', views.order_mark_ready, name='order_mark_ready'),
    path('orders/<int:pk>/assign-courier/', views.order_assign_courier, name='order_assign_courier'),
    path('orders/<int:pk>/cancel/', views.order_cancel, name='order_cancel'),
    path('orders/export/csv/', views.order_export_csv, name='order_export_csv'),
    # Courier deliveries
    path('deliveries/', views.courier_order_list, name='courier_order_list'),
    path('deliveries/<int:pk>/', views.courier_order_detail, name='courier_order_detail'),
    # Products
    path('products/', views.product_list, name='product_list'),
    path('products/new/', views.product_create, name='product_create'),
    path('products/<int:pk>/', views.product_detail, name='product_detail'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('products/<int:pk>/restore/', views.product_restore, name='product_restore'),
    path('products/<int:pk>/delete-permanent/', views.product_delete_permanent, name='product_delete_permanent'),
    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('categories/new/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_edit, name='category_edit'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('categories/<int:pk>/restore/', views.category_restore, name='category_restore'),
    path('categories/<int:pk>/delete-permanent/', views.category_delete_permanent, name='category_delete_permanent'),
    # Messages
    path('messages/', views.message_list, name='message_list'),
    path('messages/mark-all-read/', views.message_mark_all_read, name='message_mark_all_read'),
    path('messages/<int:pk>/', views.message_detail, name='message_detail'),
    path('messages/<int:pk>/delete/', views.message_delete, name='message_delete'),
    path('messages/<int:pk>/restore/', views.message_restore, name='message_restore'),
    path('messages/<int:pk>/delete-permanent/', views.message_delete_permanent, name='message_delete_permanent'),
    # Users
    path('users/', views.user_list, name='user_list'),
    path('users/<int:pk>/', views.user_detail, name='user_detail'),
    path('users/<int:pk>/toggle/', views.user_toggle_active, name='user_toggle'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),
    path('users/<int:pk>/restore/', views.user_restore, name='user_restore'),
    path('users/<int:pk>/delete-permanent/', views.user_delete_permanent, name='user_delete_permanent'),
    # Archive
    path('archive/', views.archive, name='archive'),
    # Activity Log
    path('activity/', views.activity_log, name='activity_log'),
    path('activity/user/<str:username>/', views.activity_log_user, name='activity_log_user'),
    path('activity/<int:pk>/', views.activity_log_detail, name='activity_log_detail'),
    path('activity/export/csv/', views.activity_log_export_csv, name='activity_log_export_csv'),
    # Reports
    path('reports/', views.reports, name='reports'),
    path('reports/export/excel/', views.reports_export_excel, name='reports_export_excel'),
    path('reports/expenses/add/', views.reports_expense_add, name='reports_expense_add'),
    path('reports/expenses/<int:pk>/approve/', views.reports_expense_approve, name='reports_expense_approve'),
    path('reports/expenses/<int:pk>/delete/', views.reports_expense_delete, name='reports_expense_delete'),
    path('reports/finalize/', views.reports_finalize_month, name='reports_finalize_month'),
    path('reports/reopen/', views.reports_reopen_month, name='reports_reopen_month'),
    # Livelihood Videos
    path('videos/', views.video_list, name='video_list'),
    path('videos/new/', views.video_create, name='video_create'),
    path('videos/<int:pk>/edit/', views.video_edit, name='video_edit'),
    path('videos/<int:pk>/delete/', views.video_delete, name='video_delete'),
    path('videos/<int:pk>/restore/', views.video_restore, name='video_restore'),
    path('videos/<int:pk>/delete-permanent/', views.video_delete_permanent, name='video_delete_permanent'),
    # Customer dashboard
    path('my/', views.customer_dashboard, name='customer_home'),

    # GCash QR Code Management (Staff)
    path('gcash-qr/', views.gcash_qr_manage, name='gcash_qr_manage'),
    path('gcash-qr/upload/', views.gcash_qr_upload, name='gcash_qr_upload'),
    path('gcash-qr/<int:pk>/cancel-preview/', views.gcash_qr_cancel_preview, name='gcash_qr_cancel_preview'),
    path('gcash-qr/<int:pk>/confirm/', views.gcash_qr_confirm, name='gcash_qr_confirm'),
    path('gcash-qr/<int:pk>/request-removal/', views.gcash_qr_request_removal, name='gcash_qr_request_removal'),
    # GCash QR Code Management (Admin)
    path('gcash-qr/admin/', views.gcash_qr_admin, name='gcash_qr_admin'),
    path('gcash-qr/admin/upload/', views.gcash_qr_admin_upload, name='gcash_qr_admin_upload'),
    path('gcash-qr/admin/<int:pk>/update-details/', views.gcash_qr_admin_update_details, name='gcash_qr_admin_update_details'),
    path('gcash-qr/admin/requests/<int:pk>/approve/', views.gcash_qr_request_approve, name='gcash_qr_request_approve'),
    path('gcash-qr/admin/requests/<int:pk>/reject/', views.gcash_qr_request_reject, name='gcash_qr_request_reject'),
    path('gcash-qr/admin/<int:pk>/replace/', views.gcash_qr_admin_replace, name='gcash_qr_admin_replace'),
    path('gcash-qr/admin/<int:pk>/remove/', views.gcash_qr_admin_remove, name='gcash_qr_admin_remove'),
]