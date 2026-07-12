from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/',               admin.site.urls),
    path('api/auth/',            include('autenticacion.urls')),
    path('api/catalogos/',       include('catalogos.urls')),
    path('api/',                 include('solicitudes.urls')),
]
