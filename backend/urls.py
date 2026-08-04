from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse


def health_check(_request):
    return JsonResponse({'status': 'ok'})

urlpatterns = [
    path('api/health/',          health_check, name='health-check'),
    path('admin/',               admin.site.urls),
    path('api/auth/',            include('autenticacion.urls')),
    path('api/catalogos/',       include('catalogos.urls')),
    path('api/',                 include('solicitudes.urls')),
]
