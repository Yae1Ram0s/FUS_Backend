import json
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth.models import User


class NotificacionesConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        token_str = self._get_token()
        user = await self._autenticar(token_str)
        if user is None:
            await self.close(code=4001)
            return

        self.user_id = user.id
        self.group_name = f'notificaciones_{user.id}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        pass

    async def nueva_notificacion(self, event):
        await self.send(text_data=json.dumps(event['data']))

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_token(self):
        qs = parse_qs(self.scope.get('query_string', b'').decode())
        tokens = qs.get('token', [])
        return tokens[0] if tokens else None

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
