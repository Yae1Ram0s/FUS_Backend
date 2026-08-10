import asyncio
import json

from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth.models import User

AUTH_TIMEOUT = 5  # segundos de margen para recibir el token tras conectar


class NotificacionesConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # El token ya no viaja en la query string de la URL (quedaba
        # registrado en logs de proxies/servidores intermedios y visible en
        # el panel Network/HAR de cualquiera con acceso a esos logs). Se
        # acepta la conexión sin autenticar todavía —el handshake WS no
        # expone nada por sí solo— y se espera el token como primer mensaje.
        await self.accept()
        self.autenticado = False
        self._auth_task = asyncio.ensure_future(self._cerrar_si_no_autentica())

    async def _cerrar_si_no_autentica(self):
        await asyncio.sleep(AUTH_TIMEOUT)
        if not self.autenticado:
            await self.close(code=4001)

    async def disconnect(self, code):
        auth_task = getattr(self, '_auth_task', None)
        if auth_task:
            auth_task.cancel()
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if self.autenticado:
            return  # este consumer no espera más mensajes del cliente

        try:
            data = json.loads(text_data or '{}')
        except ValueError:
            data = {}

        user = await self._autenticar(data.get('token'))
        if user is None:
            await self.close(code=4001)
            return

        self.autenticado = True
        self.user_id = user.id
        self.group_name = f'notificaciones_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)

    async def nueva_notificacion(self, event):
        await self.send(text_data=json.dumps(event['data']))

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _autenticar(self, token_str):
        if not token_str:
            return None
        try:
            from channels.db import database_sync_to_async
            token = AccessToken(token_str)
            user_id = token['user_id']

            @database_sync_to_async
            def get_user():
                try:
                    return User.objects.get(pk=user_id, is_active=True)
                except User.DoesNotExist:
                    return None

            return await get_user()
        except Exception:
            return None
