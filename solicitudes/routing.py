from django.urls import path
from .consumers import NotificacionesConsumer

websocket_urlpatterns = [
    path('ws/notificaciones/', NotificacionesConsumer.as_asgi()),
]
