from collections import defaultdict
from datetime import timedelta, timezone as dt_timezone
from statistics import median

from django.db import transaction
from django.db.models import Count, Min, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from autenticacion.admin_permissions import EsAdministradorSistema
from autenticacion.models import CorreoAutorizado

from .models import EventoUso
from .serializers import EventoUsoEntradaSerializer
from .taxonomy import (
    ACCIONES, EMBUDOS, EVENTOS, EVENTOS_SIGNIFICATIVOS, MODULOS,
    TAXONOMIA_VERSION,
)


def _snapshot_usuario(usuario):
    autorizado = (
        CorreoAutorizado.objects.select_related('unidadAdministrativa')
        .filter(email__iexact=usuario.email, activo=1)
        .first()
    )
    if not autorizado:
        return '', ''
    unidad = autorizado.unidadAdministrativa
    return autorizado.rol, (unidad.unidadAdministrativa if unidad else '')


def _porcentaje(numerador, denominador):
    return min(100.0, round(numerador * 100 / denominador, 1)) if denominador else 0.0


def _mediana(valores):
    return round(float(median(valores)), 1) if valores else 0.0


class EventosUsoView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        if isinstance(request.data, dict) and 'eventos' in request.data:
            datos = request.data['eventos']
            if not isinstance(datos, list):
                return Response({'detail': 'El campo eventos debe ser una lista.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            datos = request.data if isinstance(request.data, list) else [request.data]
        if not datos:
            return Response({'detail': 'El lote no puede estar vacío.'}, status=status.HTTP_400_BAD_REQUEST)
        if len(datos) > 50:
            return Response({'detail': 'El lote admite como máximo 50 eventos.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = EventoUsoEntradaSerializer(data=datos, many=True)
        serializer.is_valid(raise_exception=True)
        rol, unidad = _snapshot_usuario(request.user)

        # El último payload repetido en el mismo lote no reemplaza datos ya
        # existentes; el UUID es una llave de idempotencia, no de actualización.
        unicos = {}
        for payload in serializer.validated_data:
            unicos.setdefault(payload['idEvento'], payload)
        existentes = set(
            EventoUso.objects.filter(idEvento__in=unicos).values_list('idEvento', flat=True)
        )
        nuevos = [
            EventoUso(
                **payload,
                usuario=request.user,
                rolSnapshot=rol,
                unidadSnapshot=unidad,
            )
            for event_id, payload in unicos.items()
            if event_id not in existentes
        ]
        EventoUso.objects.bulk_create(nuevos, ignore_conflicts=True)
        creados = len(nuevos)
        return Response(
            {
                'recibidos': len(datos),
                'creados': creados,
                'duplicados': len(datos) - creados,
                'idsCreados': [str(obj.idEvento) for obj in nuevos],
            },
            status=status.HTTP_201_CREATED,
        )


class AdminResumenAnaliticaView(APIView):
    permission_classes = [IsAuthenticated, EsAdministradorSistema]

    def _filtros(self, request):
        try:
            dias = int(request.query_params.get('dias', 30))
        except (TypeError, ValueError):
            return None, Response({'detail': 'El parámetro dias debe ser numérico.'}, status=400)
        if not 7 <= dias <= 90:
            return None, Response({'detail': 'El parámetro dias debe estar entre 7 y 90.'}, status=400)

        rol = request.query_params.get('rol', '').strip().upper()
        unidad = request.query_params.get('unidad', '').strip()
        dispositivo = request.query_params.get('dispositivo', '').strip().upper()
        modulo = request.query_params.get('modulo', '').strip().upper()
        roles_validos = {clave for clave, _ in CorreoAutorizado.ROL_CHOICES}
        dispositivos_validos = {clave for clave, _ in EventoUso.Dispositivo.choices}
        if rol and rol not in roles_validos:
            return None, Response({'detail': 'Rol no válido.'}, status=400)
        if dispositivo and dispositivo not in dispositivos_validos:
            return None, Response({'detail': 'Dispositivo no válido.'}, status=400)
        if modulo and modulo not in MODULOS:
            return None, Response({'detail': 'Módulo no válido.'}, status=400)
        if len(unidad) > 255:
            return None, Response({'detail': 'Unidad no válida.'}, status=400)
        return {
            'dias': dias, 'rol': rol, 'unidad': unidad,
            'dispositivo': dispositivo, 'modulo': modulo,
        }, None

    def get(self, request):
        filtros, error = self._filtros(request)
        if error:
            return error
        ahora = timezone.now()
        desde = ahora - timedelta(days=filtros['dias'] - 1)
        qs = EventoUso.objects.filter(fechaServidor__gte=desde, fechaServidor__lte=ahora)
        for parametro, campo in (
            ('rol', 'rolSnapshot'), ('unidad', 'unidadSnapshot'),
            ('dispositivo', 'dispositivo'), ('modulo', 'modulo'),
        ):
            if filtros[parametro]:
                qs = qs.filter(**{campo: filtros[parametro]})

        total_eventos = qs.count()
        acciones_significativas = qs.filter(evento__in=EVENTOS_SIGNIFICATIVOS).count()
        exitos = qs.filter(evento__in=('FORM_SUBMITTED', 'TASK_COMPLETED')).count()
        errores = qs.filter(evento='TASK_FAILED').count()
        abandonos = qs.filter(evento__in=('FORM_ABANDONED', 'TASK_ABANDONED')).count()
        iniciados = qs.filter(evento__in=('FORM_STARTED', 'TASK_STARTED')).count()
        sesiones_iniciadas = qs.filter(evento__in=('FORM_STARTED', 'TASK_STARTED')).exclude(sesionId='').values('sesionId').distinct().count()
        sesiones_abandonadas = qs.filter(evento__in=('FORM_ABANDONED', 'TASK_ABANDONED')).exclude(sesionId='').values('sesionId').distinct().count()
        resultados = exitos + errores + abandonos
        duraciones = list(qs.exclude(duracionMs__isnull=True).values_list('duracionMs', flat=True))
        # `ahora`/`desde` son UTC (timezone.now() siempre lo es) — TruncDate
        # trunca por defecto en la zona local (America/Mexico_City vía
        # settings.TIME_ZONE), lo que desalinea las fechas de `diario` con
        # las de `serie` (generadas sumando días a desde.date(), en UTC) y
        # dejaba la serie diaria en cero pese a haber eventos reales. Forzar
        # UTC en ambos lados mantiene todo el conteo por día en el mismo eje.
        cobertura = qs.aggregate(
            primerEvento=Min('fechaServidor'), ultimoEvento=Max('fechaServidor'),
            diasConDatos=Count(TruncDate('fechaServidor', tzinfo=dt_timezone.utc), distinct=True),
        )

        diario = {
            row['fecha']: row for row in qs.annotate(fecha=TruncDate('fechaServidor', tzinfo=dt_timezone.utc))
            .values('fecha')
            .annotate(
                eventos=Count('idEvento'),
                usuariosActivos=Count('usuario_id', distinct=True),
                sesiones=Count('sesionId', distinct=True, filter=~Q(sesionId='')),
                accionesSignificativas=Count('idEvento', filter=Q(evento__in=EVENTOS_SIGNIFICATIVOS)),
                exitos=Count('idEvento', filter=Q(evento__in=('FORM_SUBMITTED', 'TASK_COMPLETED'))),
                errores=Count('idEvento', filter=Q(evento='TASK_FAILED')),
                abandonos=Count('idEvento', filter=Q(evento__in=('FORM_ABANDONED', 'TASK_ABANDONED'))),
            )
        }
        serie = []
        for offset in range(filtros['dias']):
            fecha = desde.date() + timedelta(days=offset)
            row = diario.get(fecha, {})
            serie.append({
                'fecha': fecha.isoformat(),
                'eventos': row.get('eventos', 0),
                'usuariosActivos': row.get('usuariosActivos', 0),
                'sesiones': row.get('sesiones', 0),
                'accionesSignificativas': row.get('accionesSignificativas', 0),
                'exitos': row.get('exitos', 0),
                'errores': row.get('errores', 0),
                'abandonos': row.get('abandonos', 0),
            })

        duracion_por_modulo = defaultdict(list)
        for nombre_modulo, duracion in qs.exclude(duracionMs__isnull=True).values_list('modulo', 'duracionMs'):
            duracion_por_modulo[nombre_modulo].append(duracion)
        filas_modulos = qs.values('modulo').annotate(
            usuariosUnicos=Count('usuario_id', distinct=True),
            sesiones=Count('sesionId', distinct=True, filter=~Q(sesionId='')),
            eventos=Count('idEvento'),
            accionesSignificativas=Count('idEvento', filter=Q(evento__in=EVENTOS_SIGNIFICATIVOS)),
            exitos=Count('idEvento', filter=Q(evento__in=('FORM_SUBMITTED', 'TASK_COMPLETED'))),
            errores=Count('idEvento', filter=Q(evento='TASK_FAILED')),
            abandonos=Count('idEvento', filter=Q(evento__in=('FORM_ABANDONED', 'TASK_ABANDONED'))),
            iniciados=Count('idEvento', filter=Q(evento__in=('FORM_STARTED', 'TASK_STARTED'))),
            sesionesIniciadas=Count('sesionId', distinct=True, filter=Q(evento__in=('FORM_STARTED', 'TASK_STARTED')) & ~Q(sesionId='')),
            sesionesAbandonadas=Count('sesionId', distinct=True, filter=Q(evento__in=('FORM_ABANDONED', 'TASK_ABANDONED')) & ~Q(sesionId='')),
        ).order_by('-accionesSignificativas', '-eventos', 'modulo')
        modulos = []
        for row in filas_modulos:
            terminales = row['exitos'] + row['errores'] + row['abandonos']
            modulos.append({
                **row,
                'tasaExito': _porcentaje(row['exitos'], terminales),
                'tasaError': _porcentaje(row['errores'], terminales),
                'tasaAbandono': _porcentaje(row['sesionesAbandonadas'], row['sesionesIniciadas']),
                'duracionMedianaMs': _mediana(duracion_por_modulo[row['modulo']]),
            })

        acciones = list(qs.values('accion').exclude(accion='').annotate(
            total=Count('idEvento'), usuariosUnicos=Count('usuario_id', distinct=True),
        ).order_by('-total', 'accion'))
        componentes = list(qs.values('modulo', 'componente').annotate(
            eventos=Count('idEvento'), usuariosUnicos=Count('usuario_id', distinct=True),
            errores=Count('idEvento', filter=Q(evento='TASK_FAILED')),
        ).order_by('-eventos', 'modulo', 'componente')[:100])
        roles_rows = list(qs.values('rolSnapshot').annotate(
            accionesSignificativas=Count('idEvento', filter=Q(evento__in=EVENTOS_SIGNIFICATIVOS)), usuariosUnicos=Count('usuario_id', distinct=True),
        ).order_by('-accionesSignificativas', 'rolSnapshot'))
        nombres_rol = dict(CorreoAutorizado.ROL_CHOICES)
        roles = [
            {'id': row['rolSnapshot'] or 'SIN_ROL', 'nombre': nombres_rol.get(row['rolSnapshot'], row['rolSnapshot'] or 'Sin rol'), **row}
            for row in roles_rows
        ]
        dispositivos_rows = list(qs.values('dispositivo').annotate(
            accionesSignificativas=Count('idEvento', filter=Q(evento__in=EVENTOS_SIGNIFICATIVOS)), usuariosUnicos=Count('usuario_id', distinct=True),
        ).order_by('-accionesSignificativas', 'dispositivo'))
        nombres_dispositivo = dict(EventoUso.Dispositivo.choices)
        dispositivos = [
            {'id': row['dispositivo'], 'nombre': nombres_dispositivo.get(row['dispositivo'], row['dispositivo']), **row}
            for row in dispositivos_rows
        ]

        snapshot_por_usuario = {}
        for row in qs.exclude(usuario_id__isnull=True).values('usuario_id', 'rolSnapshot', 'unidadSnapshot'):
            snapshot_por_usuario.setdefault(row['usuario_id'], (row['rolSnapshot'], row['unidadSnapshot']))
        duracion_por_usuario = defaultdict(list)
        for usuario_id, duracion in (
            qs.exclude(duracionMs__isnull=True).exclude(usuario_id__isnull=True)
            .values_list('usuario_id', 'duracionMs')
        ):
            duracion_por_usuario[usuario_id].append(duracion)
        filas_usuarios = qs.exclude(usuario_id__isnull=True).values('usuario_id', 'usuario__email').annotate(
            eventos=Count('idEvento'),
            accionesSignificativas=Count('idEvento', filter=Q(evento__in=EVENTOS_SIGNIFICATIVOS)),
            sesiones=Count('sesionId', distinct=True, filter=~Q(sesionId='')),
            exitos=Count('idEvento', filter=Q(evento__in=('FORM_SUBMITTED', 'TASK_COMPLETED'))),
            errores=Count('idEvento', filter=Q(evento='TASK_FAILED')),
            abandonos=Count('idEvento', filter=Q(evento__in=('FORM_ABANDONED', 'TASK_ABANDONED'))),
            modulosUsados=Count('modulo', distinct=True),
            ultimaActividad=Max('fechaServidor'),
        ).order_by('-accionesSignificativas', '-eventos')[:300]
        nombres_por_email = dict(
            CorreoAutorizado.objects.filter(
                email__in=[row['usuario__email'] for row in filas_usuarios]
            ).values_list('email', 'nombre')
        )
        usuarios = []
        for row in filas_usuarios:
            terminales = row['exitos'] + row['errores'] + row['abandonos']
            rol, unidad = snapshot_por_usuario.get(row['usuario_id'], ('', ''))
            usuarios.append({
                'id': row['usuario_id'],
                'email': row['usuario__email'],
                'nombre': nombres_por_email.get(row['usuario__email']) or row['usuario__email'],
                'rol': rol,
                'unidad': unidad,
                'eventos': row['eventos'],
                'accionesSignificativas': row['accionesSignificativas'],
                'sesiones': row['sesiones'],
                'modulosUsados': row['modulosUsados'],
                'tasaExito': _porcentaje(row['exitos'], terminales),
                'tasaError': _porcentaje(row['errores'], terminales),
                'duracionMedianaMs': _mediana(duracion_por_usuario[row['usuario_id']]),
                'ultimaActividad': row['ultimaActividad'].isoformat() if row['ultimaActividad'] else None,
            })

        embudos = []
        for modulo_nombre in qs.values_list('modulo', flat=True).distinct():
            modulo_qs = qs.filter(modulo=modulo_nombre)
            for tipo, pasos in EMBUDOS:
                conteos = {
                    row['evento']: row['sesiones'] for row in modulo_qs.filter(evento__in=pasos)
                    .values('evento').annotate(sesiones=Count('sesionId', distinct=True, filter=~Q(sesionId='')))
                }
                if not any(conteos.values()):
                    continue
                primero = conteos.get(pasos[0], 0)
                embudos.append({
                    'modulo': modulo_nombre,
                    'tipo': tipo,
                    'nombre': f'{tipo.title()} · {modulo_nombre}',
                    'conversionPct': _porcentaje(conteos.get(pasos[1], 0), primero),
                    'pasos': [
                        {'id': paso, 'nombre': paso, 'usuarios': conteos.get(paso, 0),
                         'conversionPct': _porcentaje(conteos.get(paso, 0), primero)}
                        for paso in pasos
                    ],
                })

        oportunidades = []
        for modulo_row in modulos:
            if modulo_row['accionesSignificativas'] < 5:
                continue
            if modulo_row['tasaError'] >= 20:
                oportunidades.append({
                    'prioridad': 'ALTA', 'modulo': modulo_row['modulo'], 'tipo': 'ERRORES',
                    'metrica': 'Tasa de error', 'valor': modulo_row['tasaError'],
                    'recomendacion': 'Revisar los errores más frecuentes y el flujo previo a la operación.',
                })
            if modulo_row['tasaAbandono'] >= 20:
                oportunidades.append({
                    'prioridad': 'ALTA', 'modulo': modulo_row['modulo'], 'tipo': 'ABANDONO',
                    'metrica': 'Tasa de abandono', 'valor': modulo_row['tasaAbandono'],
                    'recomendacion': 'Revisar fricción, validaciones y claridad del flujo iniciado.',
                })
            if modulo_row['duracionMedianaMs'] >= 120_000:
                oportunidades.append({
                    'prioridad': 'MEDIA', 'modulo': modulo_row['modulo'], 'tipo': 'DURACION',
                    'metrica': 'Duración mediana (ms)', 'valor': modulo_row['duracionMedianaMs'],
                    'recomendacion': 'Simplificar pasos o reducir tiempos de espera en esta tarea.',
                })

        unidades_disponibles = list(
            EventoUso.objects.exclude(unidadSnapshot='').values_list('unidadSnapshot', flat=True)
            .distinct().order_by('unidadSnapshot')
        )
        return Response({
            'generadoEn': ahora.isoformat(),
            'taxonomiaVersion': TAXONOMIA_VERSION,
            'ventana': {'dias': filtros['dias'], 'desde': desde.isoformat(), 'hasta': ahora.isoformat()},
            'cobertura': {
                'eventos': total_eventos,
                'inicio': cobertura['primerEvento'].isoformat() if cobertura['primerEvento'] else None,
                'fin': cobertura['ultimoEvento'].isoformat() if cobertura['ultimoEvento'] else None,
                'diasConDatos': cobertura['diasConDatos'] or 0,
                'estado': 'con_datos' if total_eventos else 'sin_datos',
            },
            'kpis': {
                'usuariosActivos': qs.values('usuario_id').exclude(usuario_id__isnull=True).distinct().count(),
                'sesiones': qs.exclude(sesionId='').values('sesionId').distinct().count(),
                'modulosUsados': qs.values('modulo').distinct().count(),
                'accionesSignificativas': acciones_significativas,
                'tasaExito': _porcentaje(exitos, resultados),
                'tasaError': _porcentaje(errores, resultados),
                'tasaAbandono': _porcentaje(sesiones_abandonadas, sesiones_iniciadas),
                'duracionMedianaMs': _mediana(duraciones),
            },
            'serie': serie,
            'modulos': modulos,
            'acciones': acciones,
            'componentes': componentes,
            'roles': roles,
            'dispositivos': dispositivos,
            'usuarios': usuarios,
            'embudos': embudos,
            'oportunidades': oportunidades,
            'filtros': {
                'aplicados': filtros,
                'dias': [7, 14, 30, 60, 90],
                'roles': [{'valor': clave, 'etiqueta': nombre} for clave, nombre in CorreoAutorizado.ROL_CHOICES],
                'unidades': [{'valor': nombre, 'etiqueta': nombre} for nombre in unidades_disponibles],
                'dispositivos': [{'valor': clave, 'etiqueta': nombre} for clave, nombre in EventoUso.Dispositivo.choices],
                'modulos': [{'valor': nombre, 'etiqueta': nombre.replace('_', ' ').title()} for nombre in MODULOS],
            },
            'definiciones': {
                'usuariosActivos': 'Usuarios únicos que enviaron al menos un evento durante la ventana.',
                'accionesSignificativas': 'Eventos distintos de PAGE_VIEW; representan intención o avance del usuario.',
                'tasaExito': 'FORM_SUBMITTED y TASK_COMPLETED / resultados terminales de la ventana.',
                'tasaError': 'TASK_FAILED / resultados terminales de la ventana.',
                'tasaAbandono': 'Sesiones con FORM_ABANDONED o TASK_ABANDONED / sesiones con FORM_STARTED o TASK_STARTED, limitada a 100%.',
                'duracionMedianaMs': 'Mediana de las duraciones reportadas; evita distorsión por valores extremos.',
                'embudos': 'Sesiones únicas observadas en cada paso; no son conteos de personas ni una cohorte histórica.',
            },
        })
