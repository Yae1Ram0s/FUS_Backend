from django.conf import settings
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import PushSubscription


class VapidPublicKeyView(APIView):
    """GET — llave pública VAPID que el frontend necesita para suscribirse
    (PushManager.subscribe). Sin autenticación a propósito: el registro del
    Service Worker (y la suscripción) puede pasar antes de que exista sesión
    — no es un dato sensible, es literalmente pública por diseño (RFC 8292)."""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'publicKey': getattr(settings, 'VAPID_PUBLIC_KEY', '') or ''})


class PushSuscribirView(APIView):
    """POST {endpoint, keys: {p256dh, auth}} — guarda (o actualiza) la
    suscripción Web Push de este dispositivo/navegador para el usuario
    autenticado. `endpoint` es la llave natural: si el mismo dispositivo ya
    tenía una suscripción registrada (a este u otro usuario, ej. equipo
    compartido), se actualiza en vez de duplicar."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        endpoint = (data.get('endpoint') or '').strip()
        keys = data.get('keys') or {}
        p256dh = (keys.get('p256dh') or '').strip()
        auth = (keys.get('auth') or '').strip()
        if not endpoint or not p256dh or not auth:
            return Response({'detail': 'Suscripción incompleta.'}, status=400)

        # Sin select_for_update() a propósito (no update_or_create): esto no
        # es una ruta de alta concurrencia (un dispositivo se suscribe una
        # vez, no varias veces por segundo) — el peor caso de una carrera muy
        # rara es una fila duplicada momentánea, que se autocorrige en la
        # siguiente suscripción/depuración, sin necesidad de bloquear la fila.
        existente = PushSubscription.objects.filter(endpoint=endpoint).first()
        if existente:
            existente.idUsuario = request.user
            existente.p256dh = p256dh
            existente.auth = auth
            existente.userAgent = request.META.get('HTTP_USER_AGENT', '')[:255]
            existente.save()
        else:
            PushSubscription.objects.create(
                idUsuario=request.user, endpoint=endpoint, p256dh=p256dh, auth=auth,
                userAgent=request.META.get('HTTP_USER_AGENT', '')[:255],
            )
        return Response({'detail': 'Suscripción guardada.'}, status=201)


class PushDesuscribirView(APIView):
    """POST {endpoint} — borra la suscripción de este dispositivo (se llama
    al desactivar notificaciones desde la app, o cuando el propio navegador
    invalida la suscripción anterior antes de crear una nueva)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        endpoint = (request.data.get('endpoint') or '').strip()
        if endpoint:
            PushSubscription.objects.filter(idUsuario=request.user, endpoint=endpoint).delete()
        return Response(status=204)
