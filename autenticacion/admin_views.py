import platform
import time
from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from datetime import timedelta
from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.db.migrations.executor import MigrationExecutor
from django.db import models
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from catalogos.models import UnidadAdministrativa
from .admin_permissions import EsAdministradorSistema
from .admin_serializers import RestablecerContrasenaSerializer, UsuarioAdminCrearSerializer, UsuarioAdminPatchSerializer
from .admin_services import auditar, restablecer_temporal, revocar_sesiones, seguridad, usuario_payload
from .emails import enviar_correo_otp
from .models import AuditoriaAdministrativa, CodigoOTP, CorreoAutorizado, HistorialSalud, SeguridadUsuario
from .views import _generar_otp


class AdminBaseView(APIView):
    permission_classes = [IsAuthenticated, EsAdministradorSistema]


class AdminPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'pageSize'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({'count': self.page.paginator.count, 'page': self.page.number, 'pageSize': self.get_page_size(self.request), 'totalPages': self.page.paginator.num_pages, 'results': data})


def _ultimo_admin(autorizado):
    return autorizado.rol == 'ADMIN' and autorizado.activo and CorreoAutorizado.objects.filter(rol='ADMIN', activo=1).count() <= 1


class AdminResumenView(AdminBaseView):
    def get(self, request):
        result = cache.get('admin:resumen')
        if result is None:
            total = CorreoAutorizado.objects.count()
            activos = CorreoAutorizado.objects.filter(activo=1).count()
            por_rol = {row['rol']: row['n'] for row in CorreoAutorizado.objects.filter(activo=1).values('rol').annotate(n=Count('id'))}
            result = {'usuarios': {'total': total, 'activos': activos, 'inactivos': total - activos, 'administradores': CorreoAutorizado.objects.filter(rol='ADMIN', activo=1).count(), 'porRol': por_rol}, 'seguridad': {'bloqueados': sum(1 for u in User.objects.all() if seguridad(u).bloqueadoHasta and seguridad(u).bloqueadoHasta > timezone.now()), 'requierenCambioContrasena': sum(1 for u in User.objects.all() if seguridad(u).requiereCambioContrasena)}, 'auditoriaUltimas24h': AuditoriaAdministrativa.objects.filter(fechaHora__gte=timezone.now() - timezone.timedelta(days=1)).count()}
            cache.set('admin:resumen', result, 30)
        return Response(result)


class AdminMetricasView(AdminBaseView):
    """Métricas agregadas y acotadas para el centro de supervisión ADMIN."""

    def get(self, request):
        started = time.perf_counter()
        dias = max(7, min(int(request.query_params.get('dias', 30)), 90))
        ahora = timezone.now()
        desde = ahora - timedelta(days=dias - 1)
        autorizados = CorreoAutorizado.objects.select_related('unidadAdministrativa')
        estados = list(SeguridadUsuario.objects.select_related('usuario'))
        activos = autorizados.filter(activo=1).count()
        total = autorizados.count()
        con_cuenta = User.objects.filter(email__in=autorizados.values('email')).count()
        con_ingreso = sum(1 for x in estados if x.ultimoIngreso)
        bloqueados = sum(1 for x in estados if x.bloqueadoHasta and x.bloqueadoHasta > ahora)
        fallos = sum(x.intentosFallidos for x in estados)
        otp_fallidos = CodigoOTP.objects.filter(fechaGeneracion__gte=desde).aggregate(total=models.Sum('intentosFallidos'))['total'] or 0

        ingresos_por_dia = {
            row['dia']: row['n'] for row in SeguridadUsuario.objects.filter(ultimoIngreso__gte=desde)
            .annotate(dia=TruncDate('ultimoIngreso')).values('dia').annotate(n=Count('id'))
        }
        auditoria_por_dia = {
            row['dia']: row['n'] for row in AuditoriaAdministrativa.objects.filter(fechaHora__gte=desde)
            .annotate(dia=TruncDate('fechaHora')).values('dia').annotate(n=Count('id'))
        }
        serie = [{'fecha': (desde.date() + timedelta(days=i)).isoformat(),
                  'usuariosConUltimoIngreso': ingresos_por_dia.get(desde.date() + timedelta(days=i), 0),
                  'accionesAdministrativas': auditoria_por_dia.get(desde.date() + timedelta(days=i), 0)} for i in range(dias)]
        por_unidad = list(autorizados.filter(activo=1).values(unidad=models.F('unidadAdministrativa__unidadAdministrativa')).annotate(total=Count('id')).order_by('-total')[:8])
        por_rol = list(autorizados.filter(activo=1).values('rol').annotate(total=Count('id')).order_by('-total'))
        acciones = list(AuditoriaAdministrativa.objects.filter(fechaHora__gte=desde).values('accion').annotate(total=Count('id')).order_by('-total')[:8])
        with connection.cursor() as cursor:
            db_started = time.perf_counter(); cursor.execute('SELECT 1'); cursor.fetchone()
        db_latency = round((time.perf_counter() - db_started) * 1000, 2)
        auditoria_ips = list(AuditoriaAdministrativa.objects.filter(fechaHora__gte=desde).exclude(ipCliente__isnull=True).exclude(ipCliente='').values('ipCliente').annotate(total=Count('id')).order_by('-total')[:6])
        otp_ips = list(CodigoOTP.objects.filter(fechaGeneracion__gte=desde).exclude(ipSolicitante__isnull=True).values('ipSolicitante').annotate(total=Count('id'), fallos=models.Sum('intentosFallidos')).order_by('-total')[:6])
        outstanding = OutstandingToken.objects.filter(expires_at__gt=ahora)
        sesiones = outstanding.exclude(id__in=BlacklistedToken.objects.values('token_id')).count()
        return Response({
            'generadoEn': ahora.isoformat(), 'ventanaDias': dias,
            'kpis': {'usuariosAutorizados': total, 'usuariosActivos': activos, 'coberturaCuentaPct': round(con_cuenta * 100 / total, 1) if total else 0,
                     'adopcionPct': round(con_ingreso * 100 / con_cuenta, 1) if con_cuenta else 0, 'bloqueados': bloqueados,
                     'intentosFallidosActuales': fallos, 'intentosOtpVentana': otp_fallidos},
            'serie': serie, 'porRol': por_rol, 'porUnidad': por_unidad, 'acciones': acciones,
            'red': {'latenciaBaseDatosMs': db_latency, 'latenciaEndpointMs': round((time.perf_counter() - started) * 1000, 2),
                    'sesionesVigentes': sesiones, 'ipsAdministrativasUnicas': len(auditoria_ips),
                    'ipsOtpUnicas': len(otp_ips), 'actividadPorIp': auditoria_ips, 'otpPorIp': otp_ips,
                    # CHANNEL_LAYERS siempre tiene algo asignado (Redis o el
                    # fallback en memoria, ver settings.py) — bool(...) sobre
                    # eso da True siempre y no distingue el caso peligroso
                    # (InMemoryChannelLayer con más de un worker: notificaciones
                    # que nunca llegan entre procesos, sin ningún error visible).
                    'websocketConfigurado': next(iter(getattr(settings, 'CHANNEL_LAYERS', {'default': {}}).values()), {}).get('BACKEND', '').endswith('RedisChannelLayer'),
                    'correoConfigurado': bool(settings.EMAIL_HOST_USER or 'console' in settings.EMAIL_BACKEND)},
            'definiciones': {'adopcionPct': 'Cuentas que registran al menos un último ingreso / cuentas creadas.',
                             'usuariosConUltimoIngreso': 'Usuarios cuyo último ingreso conocido ocurrió ese día; no representa todos los eventos de acceso.'},
        })


class AdminUsuariosView(AdminBaseView):
    def get(self, request):
        qs = CorreoAutorizado.objects.select_related('unidadAdministrativa').order_by('nombre', 'email')
        q = request.query_params.get('busqueda', request.query_params.get('q', '')).strip()
        if q: qs = qs.filter(Q(email__icontains=q) | Q(nombre__icontains=q))
        if request.query_params.get('rol'): qs = qs.filter(rol=request.query_params['rol'])
        if request.query_params.get('unidad'): qs = qs.filter(unidadAdministrativa_id=request.query_params['unidad'])
        activo = request.query_params.get('activo')
        if activo in ('true', 'false'): qs = qs.filter(activo=1 if activo == 'true' else 0)
        rows = list(qs)
        for key, expected in [('tiene_contrasena', 'tieneContrasena'), ('nunca_ingreso', 'nuncaIngreso'), ('bloqueado', 'bloqueado')]:
            value = request.query_params.get(key)
            if value in ('true', 'false'):
                rows = [r for r in rows if usuario_payload(r)[expected] == (value == 'true')]
        paginator = AdminPagination(); page = paginator.paginate_queryset(rows, request)
        return paginator.get_paginated_response([usuario_payload(x) for x in page])

    @transaction.atomic
    def post(self, request):
        ser = UsuarioAdminCrearSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        payload = ser.validated_data
        email = payload['email']
        if CorreoAutorizado.objects.filter(email__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            return Response({'detail': 'Este correo ya está registrado.'}, status=409)
        unidad_id = payload.get('unidadAdministrativaId')
        if unidad_id and not UnidadAdministrativa.objects.filter(pk=unidad_id, activo=1).exists():
            return Response({'detail': 'Unidad administrativa no válida o inactiva.'}, status=400)
        obj = CorreoAutorizado.objects.create(
            email=email, nombre=payload['nombre'].strip(), rol=payload['rol'],
            unidadAdministrativa_id=unidad_id, activo=1,
            idUsuarioRegistra=request.user.id,
        )
        auditar(request, 'CREAR_USUARIO_AUTORIZADO', None, {'email': email, 'rol': obj.rol})
        return Response(usuario_payload(obj), status=status.HTTP_201_CREATED)


class AdminUsuarioDetalleView(AdminBaseView):
    def _get(self, pk):
        return CorreoAutorizado.objects.select_related('unidadAdministrativa').filter(Q(pk=pk) | Q(email=User.objects.filter(pk=pk).values('email')[:1])).first()

    def get(self, request, pk):
        obj = self._get(pk)
        return Response(usuario_payload(obj)) if obj else Response({'detail': 'Usuario no encontrado.'}, status=404)

    @transaction.atomic
    def patch(self, request, pk):
        obj = self._get(pk)
        if not obj: return Response({'detail': 'Usuario no encontrado.'}, status=404)
        ser = UsuarioAdminPatchSerializer(data=request.data); ser.is_valid(raise_exception=True)
        if obj.email == request.user.email and ser.validated_data.get('rol', obj.rol) != 'ADMIN':
            return Response({'detail': 'No puedes retirar tu propio rol ADMIN.'}, status=400)
        if _ultimo_admin(obj) and ser.validated_data.get('rol', obj.rol) != 'ADMIN':
            return Response({'detail': 'Debe existir al menos un ADMIN activo.'}, status=409)
        for field in ('nombre', 'rol'):
            if field in ser.validated_data: setattr(obj, field, ser.validated_data[field])
        if 'unidadAdministrativaId' in ser.validated_data:
            unidad_id = ser.validated_data['unidadAdministrativaId']
            if unidad_id and not UnidadAdministrativa.objects.filter(pk=unidad_id).exists(): return Response({'detail': 'Unidad administrativa no válida.'}, status=400)
            obj.unidadAdministrativa_id = unidad_id
        obj.idUsuarioModifica = request.user.id; obj.save()
        user = User.objects.filter(email=obj.email).first()
        if user: user.first_name = obj.nombre; user.save(update_fields=['first_name'])
        auditar(request, 'ACTUALIZAR_USUARIO', user, {'campos': list(ser.validated_data)})
        return Response(usuario_payload(obj))

    @transaction.atomic
    def delete(self, request, pk):
        obj = self._get(pk)
        if not obj:
            return Response({'detail': 'Usuario no encontrado.'}, status=404)
        if obj.email == request.user.email:
            return Response({'detail': 'No puedes eliminar tu propia cuenta.'}, status=400)
        if _ultimo_admin(obj):
            return Response({'detail': 'Debe existir al menos un ADMIN activo.'}, status=409)
        user = User.objects.filter(email=obj.email).first()
        email = obj.email
        auditar(request, 'ELIMINAR_USUARIO', user, {'email': email, 'rol': obj.rol})
        try:
            if user:
                revocar_sesiones(user)
                user.delete()
            obj.delete()
        except ProtectedError:
            transaction.set_rollback(True)
            return Response({
                'detail': 'Este usuario tiene FUS o movimientos históricos relacionados. Desactívalo para conservar la trazabilidad.'
            }, status=409)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminUsuarioAccionView(AdminBaseView):
    accion = ''

    @transaction.atomic
    def post(self, request, pk):
        user = User.objects.filter(pk=pk).first()
        obj = CorreoAutorizado.objects.filter(email=user.email).first() if user else CorreoAutorizado.objects.filter(pk=pk).first()
        if not obj: return Response({'detail': 'Usuario no encontrado.'}, status=404)
        user = user or User.objects.filter(email=obj.email).first()
        if self.accion == 'desactivar':
            if obj.email == request.user.email: return Response({'detail': 'No puedes desactivar tu propia cuenta.'}, status=400)
            if _ultimo_admin(obj): return Response({'detail': 'Debe existir al menos un ADMIN activo.'}, status=409)
            obj.activo = 0; obj.idUsuarioModifica = request.user.id; obj.save(update_fields=['activo', 'idUsuarioModifica', 'fechaModificacion'])
            if user: user.is_active = False; user.save(update_fields=['is_active']); revocar_sesiones(user)
        elif self.accion == 'activar':
            obj.activo = 1; obj.idUsuarioModifica = request.user.id; obj.save(update_fields=['activo', 'idUsuarioModifica', 'fechaModificacion'])
            if user: user.is_active = True; user.save(update_fields=['is_active'])
        elif self.accion == 'desbloquear':
            if not user: return Response({'detail': 'La cuenta aún no ha sido activada.'}, status=409)
            sec = seguridad(user); sec.bloqueadoHasta = None; sec.intentosFallidos = 0; sec.save(update_fields=['bloqueadoHasta', 'intentosFallidos', 'fechaModificacion'])
        elif self.accion == 'cerrar_sesiones':
            if not user: return Response({'detail': 'La cuenta aún no ha sido activada.'}, status=409)
            revocar_sesiones(user)
        auditar(request, self.accion.upper(), user)
        return Response({'detail': 'Operación realizada.', 'usuario': usuario_payload(obj)})


class AdminRestablecerContrasenaView(AdminBaseView):
    def post(self, request, pk):
        ser = RestablecerContrasenaSerializer(data=request.data); ser.is_valid(raise_exception=True)
        user = User.objects.filter(pk=pk).first()
        if not user: return Response({'detail': 'La cuenta aún no ha sido activada.'}, status=409)
        if user == request.user: return Response({'detail': 'Para tu propia cuenta usa el flujo de cambio de contraseña.'}, status=400)
        if ser.validated_data['metodo'] == 'temporal':
            temporal = restablecer_temporal(user)
            auditar(request, 'RESTABLECER_CONTRASENA_TEMPORAL', user)
            return Response({'detail': 'Contraseña temporal generada.', 'passwordTemporal': temporal, 'requiereCambioContrasena': True})
        codigo = _generar_otp(user.email, request.META.get('REMOTE_ADDR'))
        enviar_correo_otp(user.email, codigo, intro='El administrador solicitó restablecer tu contraseña. Usa este código para continuar.', asunto='Restablecimiento de contraseña — SCS')
        revocar_sesiones(user); auditar(request, 'RESTABLECER_CONTRASENA_CORREO', user)
        return Response({'detail': 'Código de restablecimiento enviado.', 'enviado': True})


def _health():
    started = time.perf_counter()
    with connection.cursor() as cursor: cursor.execute('SELECT 1'); cursor.fetchone()
    latency = round((time.perf_counter() - started) * 1000, 2)
    executor = MigrationExecutor(connection)
    pending = len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    media = Path(settings.MEDIA_ROOT)
    channel_backend = next(
        iter(getattr(settings, 'CHANNEL_LAYERS', {'default': {}}).values()), {}
    ).get('BACKEND', '')
    websocket_distribuido = channel_backend.endswith('RedisChannelLayer')
    websocket = {
        'configurado': websocket_distribuido,
        'backend': channel_backend.rsplit('.', 1)[-1] or 'Sin configurar',
    }
    if not websocket_distribuido:
        websocket.update({
            'codigo': 'WS_MEMORIA_LOCAL',
            'diagnostico': (
                'Las notificaciones en tiempo real usan memoria local. '
                'WebSocket puede funcionar con un solo proceso, pero los eventos no se comparten entre procesos.'
            ),
            'impacto': (
                'En producción, algunos usuarios podrían no recibir notificaciones o actualizaciones en vivo '
                'si la petición y la conexión WebSocket llegan a procesos distintos.'
            ),
            'recomendacion': (
                'Configura una capa de canales compartida con Redis y reinicia todos los procesos del backend.'
            ),
            'comprobaciones': [
                {'etiqueta': 'Capa activa', 'valor': 'Memoria local'},
                {'etiqueta': 'Uso recomendado', 'valor': 'Desarrollo o un solo proceso'},
                {'etiqueta': 'Multiproceso', 'valor': 'No compatible'},
            ],
        })
    return {
        'estado': 'operativo' if pending == 0 and websocket_distribuido else 'atencion',
        'backend': {'ok': True, 'framework': 'Django', 'version': __import__('django').get_version()},
        'baseDatos': {'ok': True, 'motor': connection.vendor, 'latenciaMs': latency},
        'correo': {
            'configurado': bool(settings.EMAIL_HOST_USER or 'console' in settings.EMAIL_BACKEND),
            'backend': settings.EMAIL_BACKEND.rsplit('.', 1)[-1],
        },
        'websocket': websocket,
        'almacenamiento': {
            'ok': media.exists() or media.parent.exists(),
            'tipo': settings.STORAGES['default']['BACKEND'].rsplit('.', 1)[-1],
        },
        'entorno': {
            'debug': settings.DEBUG,
            'python': platform.python_version(),
            'sistema': platform.system(),
        },
        'migraciones': {'pendientes': pending},
        'seguridad': {
            'intentosOtpFallidos': CodigoOTP.objects.filter(intentosFallidos__gt=0).count(),
        },
        'generadoEn': timezone.now().isoformat(),
    }


class AdminSaludView(AdminBaseView):
    def get(self, request):
        forzar = request.query_params.get('forzar', '').lower() in ('1', 'true', 'si')
        result = None if forzar else cache.get('admin:salud')
        if result is None:
            try: result = _health()
            except Exception as exc: result = {'estado': 'degradado', 'backend': {'ok': True}, 'baseDatos': {'ok': False, 'error': exc.__class__.__name__}}
            cache.set('admin:salud', result, 45)
        return Response(result)


class AdminOTPView(AdminBaseView):
    """Supervisión del ciclo OTP sin exponer el secreto de verificación."""

    def get(self, request):
        ahora = timezone.now()
        qs = CodigoOTP.objects.all().order_by('-fechaGeneracion')
        search = request.query_params.get('search', '').strip()
        estado = request.query_params.get('estado', '').strip().upper()
        if search:
            qs = qs.filter(email__icontains=search)
        if estado in {'SIN_CONFIRMACION', 'ENVIADO', 'ERROR'}:
            qs = qs.filter(estadoEnvio=estado)

        resumen_qs = CodigoOTP.objects.filter(fechaGeneracion__gte=ahora - timedelta(days=7))
        resumen = {
            'total7d': resumen_qs.count(),
            'enviados7d': resumen_qs.filter(estadoEnvio='ENVIADO').count(),
            'errores7d': resumen_qs.filter(estadoEnvio='ERROR').count(),
            'sinConfirmacion7d': resumen_qs.filter(estadoEnvio='SIN_CONFIRMACION').count(),
        }
        paginator = AdminPagination()
        page = paginator.paginate_queryset(qs, request)
        resultados = [{
            'id': otp.id,
            'email': otp.email,
            'fechaGeneracion': otp.fechaGeneracion.isoformat(),
            'fechaExpiracion': otp.fechaExpiracion.isoformat(),
            'estadoEnvio': otp.estadoEnvio,
            'fechaEnvio': otp.fechaEnvio.isoformat() if otp.fechaEnvio else None,
            'detalleEnvio': otp.detalleEnvio,
            'usado': bool(otp.usado),
            'expirado': otp.fechaExpiracion <= ahora,
            'intentosFallidos': otp.intentosFallidos,
            'ipSolicitante': otp.ipSolicitante,
        } for otp in page]
        response = paginator.get_paginated_response(resultados)
        response.data['resumen'] = resumen
        return response


class AdminAuditoriaView(AdminBaseView):
    def get(self, request):
        qs = AuditoriaAdministrativa.objects.all()
        if request.query_params.get('accion'): qs = qs.filter(accion=request.query_params['accion'])
        if request.query_params.get('actor'): qs = qs.filter(actorEmail__icontains=request.query_params['actor'])
        if request.query_params.get('objetivo'): qs = qs.filter(objetivoEmail__icontains=request.query_params['objetivo'])
        paginator = AdminPagination(); page = paginator.paginate_queryset(qs, request)
        data = [{'id': x.id, 'fechaHora': x.fechaHora.isoformat(), 'actorEmail': x.actorEmail, 'objetivoEmail': x.objetivoEmail, 'accion': x.accion, 'detalle': x.detalle, 'ipCliente': x.ipCliente} for x in page]
        return paginator.get_paginated_response(data)


class AdminAuditoriaSerieView(AdminBaseView):
    """Conteo de acciones administrativas por día, para graficar actividad
    reciente — la lista paginada de AdminAuditoriaView no sirve para esto
    (agregar del lado del cliente sobre datos paginados no escala)."""

    def get(self, request):
        dias = max(1, min(int(request.query_params.get('dias', 14)), 90))
        desde = timezone.localtime(timezone.now()).date() - timedelta(days=dias - 1)
        conteos = {
            row['dia']: row['n']
            for row in AuditoriaAdministrativa.objects.filter(fechaHora__date__gte=desde)
                .annotate(dia=TruncDate('fechaHora')).values('dia').annotate(n=Count('id'))
        }
        serie = [
            {'fecha': (desde + timedelta(days=i)).isoformat(), 'total': conteos.get(desde + timedelta(days=i), 0)}
            for i in range(dias)
        ]
        return Response(serie)


class AdminSaludHistorialView(AdminBaseView):
    """Fotos de `_health()` guardadas por `registrar_salud_sistema` — permite
    graficar disponibilidad/latencia en el tiempo en vez de solo el instante
    actual que ya expone AdminSaludView."""

    def get(self, request):
        dias = max(1, min(int(request.query_params.get('dias', 14)), 90))
        desde = timezone.now() - timedelta(days=dias)
        qs = HistorialSalud.objects.filter(fechaHora__gte=desde).order_by('fechaHora')
        data = [{
            'fechaHora': x.fechaHora.isoformat(),
            'estado': x.estado,
            'latenciaMs': (x.detalle.get('baseDatos') or {}).get('latenciaMs'),
        } for x in qs]
        return Response(data)
