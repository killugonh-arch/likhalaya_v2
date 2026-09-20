from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

handler404 = 'likhalaya_project.views.error_404'
handler403 = 'likhalaya_project.views.error_403'
handler500 = 'likhalaya_project.views.error_500'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('store.urls')),
    path('accounts/', include('accounts.urls')),
    path('orders/', include('orders.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('api/', include('api.urls')),
]

# only serve media locally, cloudinary handles it in production
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)