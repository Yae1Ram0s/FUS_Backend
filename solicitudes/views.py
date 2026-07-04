import hashlib
import os

ALLOWED_MIME_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.docx'}
MAX_FILE_SIZE      = 10 * 1024 * 1024   # 10 MB por archivo
MAX_TOTAL_SIZE     = 30 * 1024 * 1024   # 30 MB por FUS


def _validar_archivo(archivo):
    ext  = os.path.splitext(archivo.name)[1].lower()
    mime = (archivo.content_type or '').split(';')[0].strip()
    if ext not in ALLOWED_EXTENSIONS:
        return f'Extensión no permitida: {ext}. Usa PDF, JPG, PNG o DOCX.'
    if mime and mime not in ALLOWED_MIME_TYPES:
        return f'Tipo de archivo no permitido: {mime}.'
    if archivo.size > MAX_FILE_SIZE:
        return f'"{archivo.name}" supera 10 MB.'
    return None


from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.exceptions import PermissionDenied

from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion
from .models import FUS, Evidencia, Turnado, Seguimiento, Bitacora, Notificacion
from .serializers import FUSSerializer, TurnadoSerializer, TurnadoActividadSerializer, SeguimientoSerializer, NotificacionSerializer
from .utils import get_rol, log_bitacora


def _push_notificacion(notif):
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    group_name = f'notificaciones_{notif.idDestinatario_id}'
    data = {
        'id':            str(notif.id),
        'fusFolio':      notif.fusFolio,
        'tipo':          notif.tipoEvento,
        'mensaje':       notif.mensaje,
        'leida':         False,
        'fechaCreacion': notif.fechaGeneracion.isoformat(),
    }
    async_to_sync(channel_layer.group_send)(
        group_name,
        {'type': 'nueva_notificacion', 'data': data},
    )


# ── Helpers ─────────────────────────────────────────────────────────────────

# _rol/_log se mantienen como alias locales para no tocar cada llamada existente.
_rol = get_rol
_log = log_bitacora


_ROL_FOLIO = {'ROL1': 'PARTICULAR', 'ROL2': 'TITULAR'}

def _generar_folio(rol, year):
    from django.db import transaction
    with transaction.atomic():
        seq = FUS.objects.select_for_update().filter(fechaRegistro__year=year).count() + 1
        segmento = _ROL_FOLIO.get(rol, rol)
        return f"ANAM/{segmento}/FUS/{seq:04d}/{year}"


def _sha256(f):
    h = hashlib.sha256()
    for chunk in f.chunks():
        h.update(chunk)
    return h.hexdigest()


# ── FUS ─────────────────────────────────────────────────────────────────────

class FUSListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get(self, request):
        if _rol(request.user) != 'ROL1':
            return Response({'detail': 'No autorizado.'}, status=403)

        qs = FUS.objects.filter(activo=1).select_related(
            'idSolicitanteInterno', 'idMedioRecepcion'
        ).prefetch_related('evidencias')

        estatus = request.query_params.get('estatusParticular')
        search  = request.query_params.get('search')
        if estatus:
            qs = qs.filter(estatusParticular_id=estatus)
        if search:
            qs = qs.filter(folio__icontains=search) | qs.filter(descripcion__icontains=search)

        qs = qs.order_by('-fechaRegistro')

        # Paginación
        try:
            page     = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 30))))
        except (ValueError, TypeError):
            page, page_size = 1, 30

        total  = qs.count()
        offset = (page - 1) * page_size
        data   = FUSSerializer(qs[offset: offset + page_size], many=True).data
        return Response({'total': total, 'page': page, 'page_size': page_size, 'results': data})

    def post(self, request):
        user  = request.user
        rol   = _rol(user)
        if rol != 'ROL1':
            return Response({'detail': 'No autorizado.'}, status=403)

        data  = request.data
        ip    = request.META.get('REMOTE_ADDR')
        now   = timezone.now()
        year  = now.year
        folio = _generar_folio(rol, year)

        medio_id = data.get('idMedioRecepcion')
        medio    = get_object_or_404(MedioRecepcion, pk=medio_id) if medio_id else None

        nombre_ext = data.get('nombreExterno', '').strip() or None
        tel_ext    = data.get('telefonoExterno', '').strip() or None
        correo_ext = data.get('correoExterno', '').strip() or None

        fus = FUS.objects.create(
            folio=folio,
            idSolicitanteInterno=user,
            fechaHora=now,
            descripcion=data.get('descripcion', ''),
            contexto=data.get('contexto', ''),
            idMedioRecepcion=medio,
            medioEspecificacion=data.get('medioEspecificacion', ''),
            prioridad=data.get('prioridad') or None,
            nombreExterno=nombre_ext,
            telefonoExterno=tel_ext,
            correoExterno=correo_ext,
            estatusParticular_id='Registrado',
            idUsuarioRegistra=user.id,
        )

        # Evidencias — validar antes de guardar
        from django.conf import settings
        archivos = request.FILES.getlist('evidencias')
        total_size = sum(a.size for a in archivos)
        if total_size > MAX_TOTAL_SIZE:
            fus.delete()
            return Response(
                {'detail': 'El total de archivos supera 30 MB.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        for archivo in archivos:
            err = _validar_archivo(archivo)
            if err:
                fus.delete()
                return Response({'detail': err}, status=status.HTTP_400_BAD_REQUEST)

        for archivo in archivos:
            sha = _sha256(archivo)
            nombre_seguro = os.path.basename(archivo.name)
            ruta_rel = f"evidencias/{fus.pk}/{nombre_seguro}"
            ruta_abs = os.path.join(settings.MEDIA_ROOT, ruta_rel)
            os.makedirs(os.path.dirname(ruta_abs), exist_ok=True)
            with open(ruta_abs, 'wb') as dest:
                for chunk in archivo.chunks():
                    dest.write(chunk)
            Evidencia.objects.create(
                idFus=fus,
                nombreArchivo=nombre_seguro,
                rutaArchivo=ruta_rel,
                tipoMime=archivo.content_type,
                hashSha256=sha,
                idUsuarioRegistra=user.id,
            )

        _log(usuario=user.email, rol=rol, accion='REGISTRO_FUS',
             ip=ip, folio=folio, estado_nuevo='Registrado')

        return Response(FUSSerializer(fus).data, status=status.HTTP_201_CREATED)


class TurnarFUSView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        rol  = _rol(user)
        if rol != 'ROL1':
            return Response({'detail': 'No autorizado.'}, status=403)

        fus           = get_object_or_404(FUS, pk=pk, activo=1)
        ip            = request.META.get('REMOTE_ADDR')
        destinatarios = request.data.get('destinatarios', [])
        solicitud_txt = request.data.get('solicitudTexto', '')
        now           = timezone.now()

        if not destinatarios:
            return Response({'detail': 'Se requiere al menos un destinatario.'}, status=400)

        # Solo se puede turnar si el FUS está en Registrado o Turnado
        if fus.estatusParticular_id not in ('Registrado', 'Turnado'):
            return Response(
                {'detail': f'No se puede turnar un FUS en estado "{fus.estatusParticular_id}".'},
                status=400,
            )

        # Nombre del remitente (ROL1) para las notificaciones
        remitente_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
        nombre_remitente = remitente_auth.nombre if remitente_auth else (user.first_name or user.email)

        for dest in destinatarios:
            dest_user = get_object_or_404(User, pk=dest['idDestinatario'])
            medio     = get_object_or_404(MedioRecepcion, pk=dest['idMedio'])
            Turnado.objects.create(
                idFus=fus,
                idRemitente=user,
                idDestinatario=dest_user,
                idMedio=medio,
                solicitudTexto=solicitud_txt,
                fechaHoraTurnado=now,
                idUsuarioRegistra=user.id,
            )
            _notif = Notificacion.objects.create(
                idDestinatario=dest_user,
                fusFolio=fus.folio,
                tipoEvento='TURNADO',
                mensaje=f"{nombre_remitente} te ha turnado el FUS {fus.folio}.",
            )
            _push_notificacion(_notif)

        estado_ant = fus.estatusParticular_id
        fus.estatusParticular_id = 'Turnado'
        fus.idUsuarioModifica = user.id
        fus.save()

        _log(usuario=user.email, rol=rol, accion='TURNAR_FUS',
             ip=ip, folio=fus.folio, estado_ant=estado_ant, estado_nuevo='Turnado')

        return Response({'detail': 'FUS turnado correctamente.'})


# ── Actividad de un FUS (ROL1 solo lectura) ──────────────────────────────────

class FUSActividadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if _rol(request.user) != 'ROL1':
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(FUS, pk=pk, activo=1)
        turnados = Turnado.objects.filter(
            idFus=fus, activo=1
        ).select_related(
            'idDestinatario', 'idRemitente', 'idMedio',
        ).prefetch_related(
            'seguimientos',
        ).order_by('fechaHoraTurnado')
        return Response(TurnadoActividadSerializer(turnados, many=True).data)


# ── Turnados (ROL2) ──────────────────────────────────────────────────────────

class MisTurnadosView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Turnado.objects.filter(
            idDestinatario=request.user, activo=1
        ).select_related(
            'idFus', 'idFus__idSolicitanteInterno', 'idFus__idMedioRecepcion',
            'idRemitente', 'idMedio',
        )

        estatus = request.query_params.get('estatusTitular')
        search  = request.query_params.get('search')
        if estatus:
            qs = qs.filter(estatusTitular_id=estatus)
        if search:
            qs = qs.filter(idFus__folio__icontains=search) | qs.filter(idFus__descripcion__icontains=search)

        qs = qs.order_by('-fechaRegistro')

        # Paginación
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 30))))
        except (ValueError, TypeError):
            page, page_size = 1, 30

        total  = qs.count()
        offset = (page - 1) * page_size
        data   = TurnadoSerializer(qs[offset: offset + page_size], many=True).data
        return Response({'total': total, 'page': page, 'page_size': page_size, 'results': data})


class ConcluirTurnadoView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        turnado = get_object_or_404(Turnado, pk=pk, activo=1, idDestinatario=request.user)

        if turnado.estatusTitular_id == 'Concluido':
            return Response({'detail': 'El asunto ya está concluido.'}, status=400)

        # Condición obligatoria: debe existir al menos una respuesta registrada
        tiene_respuestas = Seguimiento.objects.filter(idTurnado=turnado, activo=1).exists()
        if not tiene_respuestas:
            return Response(
                {'detail': 'Debes registrar al menos una respuesta de seguimiento antes de concluir el asunto.'},
                status=400,
            )

        user    = request.user
        ip      = request.META.get('REMOTE_ADDR')
        rol     = _rol(user)
        est_ant = turnado.estatusTitular_id

        turnado.estatusTitular_id    = 'Concluido'
        turnado.idUsuarioModifica = user.id
        turnado.save()

        _log(usuario=user.email, rol=rol, accion='CONCLUSION_FUS',
             ip=ip, folio=turnado.idFus.folio,
             estado_ant=est_ant, estado_nuevo='Concluido')

        # Si TODOS los turnados activos del FUS están concluidos → FUS pasa a Concluido
        fus        = turnado.idFus
        pendientes = fus.turnados.filter(activo=1).exclude(estatusTitular_id='Concluido').count()
        if pendientes == 0:
            est_ant_fus              = fus.estatusParticular_id
            fus.estatusParticular_id = 'Concluido'
            fus.fechaConclusion   = timezone.now()
            fus.idUsuarioModifica = user.id
            fus.save()

            concluye_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
            nombre_concluye = concluye_auth.nombre if concluye_auth else (user.first_name or user.email)
            _notif = Notificacion.objects.create(
                idDestinatario=fus.idSolicitanteInterno,
                fusFolio=fus.folio,
                tipoEvento='CONCLUIDO',
                mensaje=f"{nombre_concluye} ha concluido el FUS {fus.folio}.",
            )
            _push_notificacion(_notif)

            _log(usuario=user.email, rol=rol, accion='ASIGNACION_ESTADO',
                 ip=ip, folio=fus.folio,
                 estado_ant=est_ant_fus, estado_nuevo='Concluido')

        return Response({'detail': 'Asunto concluido correctamente.'})


# ── Seguimientos ─────────────────────────────────────────────────────────────

class SeguimientoListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)
        if turnado.idDestinatario_id != request.user.id:
            return Response({'detail': 'No autorizado.'}, status=403)
        qs      = Seguimiento.objects.filter(idTurnado=turnado, activo=1).order_by('fechaActividad')
        return Response(SeguimientoSerializer(qs, many=True).data)

    def post(self, request, turnado_id):
        turnado = get_object_or_404(Turnado, pk=turnado_id, activo=1)
        if turnado.idDestinatario_id != request.user.id:
            return Response({'detail': 'No autorizado.'}, status=403)

        # Guard: bloquear si el asunto ya está concluido
        if turnado.estatusTitular_id == 'Concluido':
            return Response(
                {'detail': 'No se pueden agregar respuestas a un asunto ya concluido.'},
                status=400,
            )

        user = request.user
        ip   = request.META.get('REMOTE_ADDR')
        rol  = _rol(user)

        seg = Seguimiento.objects.create(
            idTurnado=turnado,
            fechaActividad=request.data.get('fechaActividad') or None,
            descripcionActividad=request.data.get('descripcionActividad', ''),
            accionTexto=request.data.get('accionTexto') or None,
            idUsuarioRegistra=user.id,
        )

        # Nombre del titular (ROL2) para las notificaciones
        titular_auth = CorreoAutorizado.objects.filter(email=user.email, activo=1).first()
        nombre_titular = titular_auth.nombre if titular_auth else (user.first_name or user.email)

        fus = turnado.idFus

        # Transición Recibido → En_seguimiento (primera respuesta del titular)
        if turnado.estatusTitular_id == 'Recibido':
            turnado.estatusTitular_id = 'En_seguimiento'
            turnado.idUsuarioModifica = user.id
            turnado.save()

            # Transición FUS: Turnado → Atendido (cuando al menos un titular responde)
            if fus.estatusParticular_id == 'Turnado':
                fus.estatusParticular_id = 'Atendido'
                fus.idUsuarioModifica = user.id
                fus.save()

                _notif = Notificacion.objects.create(
                    idDestinatario=fus.idSolicitanteInterno,
                    fusFolio=fus.folio,
                    tipoEvento='CAMBIO_ESTADO',
                    mensaje=f"{nombre_titular} comenzó a atender el FUS {fus.folio}.",
                )
                _push_notificacion(_notif)

                _log(usuario=user.email, rol=rol, accion='ASIGNACION_ESTADO',
                     ip=ip, folio=fus.folio,
                     estado_ant='Turnado', estado_nuevo='Atendido',
                     obs=f'Primera respuesta registrada por {nombre_titular}')
        else:
            # Seguimientos posteriores — notificar al ROL1 cada nueva respuesta
            resumen = seg.descripcionActividad[:80]
            if len(seg.descripcionActividad) > 80:
                resumen += '…'
            _notif = Notificacion.objects.create(
                idDestinatario=fus.idSolicitanteInterno,
                fusFolio=fus.folio,
                tipoEvento='RESPUESTA',
                mensaje=f"{nombre_titular} registró una nueva respuesta en el FUS {fus.folio}: \"{resumen}\"",
            )
            _push_notificacion(_notif)

        _log(usuario=user.email, rol=rol, accion='REGISTRO_RESPUESTA',
             ip=ip, folio=fus.folio)

        return Response(SeguimientoSerializer(seg).data, status=status.HTTP_201_CREATED)


class SeguimientoDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        seg = get_object_or_404(Seguimiento, pk=pk, activo=1)
        if seg.idTurnado.idDestinatario_id != request.user.id:
            return Response({'detail': 'No autorizado.'}, status=403)

        # Guard: bloquear si el asunto está concluido
        if seg.idTurnado.estatusTitular_id == 'Concluido':
            return Response(
                {'detail': 'No se pueden eliminar respuestas de un asunto ya concluido.'},
                status=400,
            )

        seg.activo = 0
        seg.save()
        return Response(status=status.HTTP_204_NO_CONTENT)




# ── Notificaciones ────────────────────────────────────────────────────────────

class NotificacionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notificacion.objects.filter(
            idDestinatario=request.user
        ).order_by('-fechaGeneracion')

        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 50))))
        except (ValueError, TypeError):
            page, page_size = 1, 50

        total  = qs.count()
        offset = (page - 1) * page_size
        data   = NotificacionSerializer(qs[offset: offset + page_size], many=True).data
        return Response({'total': total, 'page': page, 'page_size': page_size, 'results': data})


class NotificacionMarcarLeidaView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        notif = get_object_or_404(Notificacion, pk=pk, idDestinatario=request.user)
        notif.leida = 1
        notif.fechaLectura = timezone.now()
        notif.save()
        return Response(NotificacionSerializer(notif).data)


class NotificacionMarcarTodasView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        Notificacion.objects.filter(
            idDestinatario=request.user, leida=0
        ).update(leida=1, fechaLectura=timezone.now())
        return Response({'detail': 'Todas marcadas como leídas.'})


# ── Bitácora ──────────────────────────────────────────────────────────────────

ROL1_ACCIONES = ['REGISTRO_RESPUESTA', 'CONCLUSION_FUS', 'ASIGNACION_ESTADO']
ROL2_ACCIONES = ['CONCLUSION_FUS', 'REGISTRO_RESPUESTA', 'REGISTRO_ACCION']


def _bitacora_base_qs(request):
    """Devuelve el queryset de bitácora ya filtrado por rol del usuario."""
    rol = _rol(request.user)
    if rol == 'ROL1':
        return Bitacora.objects.all()
    elif rol == 'ROL2':
        return Bitacora.objects.filter(
            usuario=request.user.email, accion__in=ROL2_ACCIONES
        )
    return Bitacora.objects.none()


def _aplicar_filtros_bitacora(qs, params, rol):
    usuario     = params.get('usuario')
    accion      = params.get('accion')
    folio       = params.get('folio')
    fecha_desde = params.get('fecha_desde')
    fecha_hasta = params.get('fecha_hasta')

    if usuario and rol == 'ROL1': qs = qs.filter(usuario__icontains=usuario)
    if accion:      qs = qs.filter(accion=accion)
    if folio:       qs = qs.filter(fusFolio__icontains=folio)
    if fecha_desde: qs = qs.filter(fechaHora__date__gte=fecha_desde)
    if fecha_hasta: qs = qs.filter(fechaHora__date__lte=fecha_hasta)
    return qs


class BitacoraListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rol = _rol(request.user)
        qs  = _bitacora_base_qs(request).order_by('-fechaHora')
        qs  = _aplicar_filtros_bitacora(qs, request.query_params, rol)

        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(100, max(1, int(request.query_params.get('page_size', 50))))
        except (ValueError, TypeError):
            page, page_size = 1, 50

        total  = qs.count()
        offset = (page - 1) * page_size

        from .serializers import BitacoraSerializer
        pagina = list(qs[offset: offset + page_size])
        nombres_map = dict(
            CorreoAutorizado.objects.filter(
                email__in={r.usuario for r in pagina}
            ).values_list('email', 'nombre')
        )
        data = BitacoraSerializer(pagina, many=True, context={'nombres_map': nombres_map}).data
        return Response({
            'total': total, 'page': page, 'page_size': page_size,
            'results': data, 'rol': rol,
        })


# ── Exportar Bitácora ────────────────────────────────────────────────────────

class ExportarBitacoraExcelView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import openpyxl
        from django.http import HttpResponse
        from openpyxl.styles import Font, PatternFill, Alignment

        rol = _rol(request.user)
        qs  = _bitacora_base_qs(request).order_by('-fechaHora')
        qs  = _aplicar_filtros_bitacora(qs, request.query_params, rol)

        ACCION_LABELS = {
            'REGISTRO_FUS': 'Registro FUS', 'TURNAR_FUS': 'Turnar FUS',
            'ASIGNACION_ESTADO': 'Cambio de estado', 'REGISTRO_RESPUESTA': 'Registro respuesta',
            'REGISTRO_ACCION': 'Registro acción', 'CONCLUSION_FUS': 'Conclusión FUS',
            'INICIO_SESION': 'Inicio sesión', 'CIERRE_SESION': 'Cierre sesión',
            'RESTABLECER_CONTRASENA': 'Restablecer contraseña',
            'ELIMINACION': 'Eliminación',
        }

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Bitácora'

        headers = ['Fecha y hora', 'Usuario', 'Rol', 'Acción', 'Folio',
                   'Estado anterior', 'Estado nuevo', 'IP', 'Observaciones']
        ws.append(headers)

        fill = PatternFill('solid', fgColor='9F2241')
        font = Font(bold=True, color='FFFFFF', size=11)
        for cell in ws[1]:
            cell.fill = fill
            cell.font = font
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        fmt = lambda d: d.strftime('%d/%m/%Y %H:%M:%S') if d else ''
        for r in qs:
            ws.append([
                fmt(r.fechaHora), r.usuario, r.rol,
                ACCION_LABELS.get(r.accion, r.accion),
                r.fusFolio or '', r.estadoAnterior or '', r.estadoNuevo or '',
                r.ipCliente or '', r.observaciones or '',
            ])

        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(
                max(len(str(cell.value or '')) for cell in col) + 4, 50
            )
        ws.freeze_panes = 'A2'

        resp = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        resp['Content-Disposition'] = 'attachment; filename="bitacora.xlsx"'
        wb.save(resp)
        return resp


class ExportarBitacoraPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        import io

        rol = _rol(request.user)
        qs  = _bitacora_base_qs(request).order_by('-fechaHora')
        qs  = _aplicar_filtros_bitacora(qs, request.query_params, rol)

        ACCION_LABELS = {
            'REGISTRO_FUS': 'Registro FUS', 'TURNAR_FUS': 'Turnar FUS',
            'ASIGNACION_ESTADO': 'Cambio de estado', 'REGISTRO_RESPUESTA': 'Registro respuesta',
            'REGISTRO_ACCION': 'Registro acción', 'CONCLUSION_FUS': 'Conclusión FUS',
            'INICIO_SESION': 'Inicio sesión', 'CIERRE_SESION': 'Cierre sesión',
            'RESTABLECER_CONTRASENA': 'Restablecer contraseña',
            'ELIMINACION': 'Eliminación',
        }

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                leftMargin=1.2*cm, rightMargin=1.2*cm,
                                topMargin=1.2*cm, bottomMargin=1.2*cm)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('title', parent=styles['Heading1'],
                                     fontSize=15, textColor=colors.HexColor('#9F2241'), spaceAfter=6)
        cell_style  = ParagraphStyle('cell', parent=styles['Normal'], fontSize=7.5, leading=10)

        elements = [Paragraph('Bitácora de auditoría — ANAM', title_style), Spacer(1, 0.3*cm)]

        fmt = lambda d: d.strftime('%d/%m/%Y %H:%M') if d else '—'
        data = [['Fecha y hora', 'Usuario', 'Rol', 'Acción', 'Folio', 'Est. ant.', 'Est. nuevo']]
        for r in qs:
            data.append([
                Paragraph(fmt(r.fechaHora), cell_style),
                Paragraph(r.usuario, cell_style),
                Paragraph(r.rol, cell_style),
                Paragraph(ACCION_LABELS.get(r.accion, r.accion), cell_style),
                Paragraph(r.fusFolio or '—', cell_style),
                Paragraph(r.estadoAnterior or '—', cell_style),
                Paragraph(r.estadoNuevo or '—', cell_style),
            ])

        t = Table(data, colWidths=[3.8*cm, 5*cm, 1.8*cm, 3.5*cm, 4*cm, 2.5*cm, 2.5*cm], repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9F2241')),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, 0), 8.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F4F6')]),
            ('GRID',       (0, 0), (-1, -1), 0.4, colors.HexColor('#DDD0D5')),
            ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(t)

        doc.build(elements)
        buf.seek(0)
        resp = HttpResponse(buf, content_type='application/pdf')
        resp['Content-Disposition'] = 'attachment; filename="bitacora.pdf"'
        return resp


# ── Exportar FUS ──────────────────────────────────────────────────────────────

def _fus_queryset(request):
    if _rol(request.user) != 'ROL1':
        raise PermissionDenied('No autorizado.')
    qs = FUS.objects.filter(activo=1).select_related(
        'idSolicitanteInterno', 'idMedioRecepcion'
    ).order_by('-fechaRegistro')
    estatus = request.query_params.get('estatusParticular')
    search  = request.query_params.get('search')
    if estatus: qs = qs.filter(estatusParticular_id=estatus)
    if search:  qs = qs.filter(folio__icontains=search) | qs.filter(descripcion__icontains=search)
    return qs


class ExportarFUSExcelView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import openpyxl
        from django.http import HttpResponse

        qs = _fus_queryset(request)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Solicitudes FUS'

        headers = ['Folio', 'Fecha', 'Solicitante', 'Medio', 'Prioridad',
                   'Estatus', 'Descripción', 'Contexto']
        ws.append(headers)

        from openpyxl.styles import Font, PatternFill, Alignment
        header_fill = PatternFill('solid', fgColor='9F2241')
        header_font = Font(bold=True, color='FFFFFF', size=11)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

        fmt = lambda d: d.strftime('%d/%m/%Y %H:%M') if d else ''
        fmt_date = lambda d: d.strftime('%d/%m/%Y') if d else ''

        for fus in qs:
            sol = fus.idSolicitanteInterno
            nombre_sol = f"{sol.first_name} {sol.last_name}".strip() if sol else ''
            ws.append([
                fus.folio,
                fmt(fus.fechaHora),
                nombre_sol or (sol.email if sol else ''),
                fus.idMedioRecepcion.nombreMedio if fus.idMedioRecepcion else '',
                fus.prioridad or '',
                fus.estatusParticular_id,
                fus.descripcion,
                fus.contexto or '',
            ])

        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

        ws.freeze_panes = 'A2'

        response = HttpResponse(
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="solicitudes_fus.xlsx"'
        wb.save(response)
        return response


class ExportarFUSPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import HttpResponse
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        import io

        qs = _fus_queryset(request)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                                leftMargin=1.5*cm, rightMargin=1.5*cm,
                                topMargin=1.5*cm, bottomMargin=1.5*cm)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('title', parent=styles['Heading1'],
                                     fontSize=16, textColor=colors.HexColor('#9F2241'),
                                     spaceAfter=6)
        cell_style = ParagraphStyle('cell', parent=styles['Normal'], fontSize=8, leading=10)

        elements = [
            Paragraph('Reporte de Solicitudes FUS — ANAM', title_style),
            Spacer(1, 0.3*cm),
        ]

        fmt = lambda d: d.strftime('%d/%m/%Y %H:%M') if d else '—'
        fmt_date = lambda d: d.strftime('%d/%m/%Y') if d else '—'

        data = [['Folio', 'Fecha', 'Solicitante', 'Prioridad', 'Estatus', 'Descripción']]
        for fus in qs:
            sol = fus.idSolicitanteInterno
            nombre_sol = f"{sol.first_name} {sol.last_name}".strip() if sol else (sol.email if sol else '—')
            desc = fus.descripcion[:120] + ('…' if len(fus.descripcion) > 120 else '')
            data.append([
                Paragraph(fus.folio, cell_style),
                Paragraph(fmt(fus.fechaHora), cell_style),
                Paragraph(nombre_sol, cell_style),
                Paragraph(fus.prioridad or '—', cell_style),
                Paragraph(fus.estatusParticular_id, cell_style),
                Paragraph(desc, cell_style),
            ])

        col_widths = [4*cm, 3.5*cm, 3.5*cm, 2*cm, 2.5*cm, None]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9F2241')),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, 0), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F9F4F6')]),
            ('GRID',       (0, 0), (-1, -1), 0.4, colors.HexColor('#DDD0D5')),
            ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        elements.append(t)

        doc.build(elements)
        buf.seek(0)
        response = HttpResponse(buf, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="solicitudes_fus.pdf"'
        return response


# ── Descargar FUS individual (PDF) ────────────────────────────────────────────

class DescargarFUSPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, folio):
        from django.http import HttpResponse
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import cm
        import io

        try:
            fus = FUS.objects.select_related(
                'idSolicitanteInterno', 'idMedioRecepcion', 'estatusParticular'
            ).get(folio=folio, activo=1)
        except FUS.DoesNotExist:
            from rest_framework.response import Response
            return Response({'detail': 'FUS no encontrado.'}, status=404)

        bitacora = Bitacora.objects.filter(fusFolio=folio).order_by('fechaHora')

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        W = A4[0] - 4*cm  # usable width ≈ 17 cm

        VERDE  = colors.HexColor('#1F5647')
        DORADO = colors.HexColor('#BC955C')
        CLARO  = colors.HexColor('#F0F5F3')
        BORDE  = colors.HexColor('#C3D4CF')

        styles = getSampleStyleSheet()

        st_titulo = ParagraphStyle('titulo', fontName='Helvetica-Bold', fontSize=18,
                                   textColor=VERDE, spaceAfter=2)
        st_folio  = ParagraphStyle('folio',  fontName='Helvetica-Bold', fontSize=11,
                                   textColor=DORADO, spaceAfter=8)
        st_sec    = ParagraphStyle('sec',    fontName='Helvetica-Bold', fontSize=9,
                                   textColor=colors.white, spaceAfter=0)
        st_lbl    = ParagraphStyle('lbl',    fontName='Helvetica-Bold', fontSize=8,
                                   textColor=colors.HexColor('#3a3a3a'))
        st_val    = ParagraphStyle('val',    fontName='Helvetica',      fontSize=8,
                                   textColor=colors.HexColor('#1a1a1a'), leading=11)
        st_bita   = ParagraphStyle('bita',   fontName='Helvetica',      fontSize=7,
                                   textColor=colors.HexColor('#1a1a1a'), leading=10)

        fmt = lambda d: d.strftime('%d/%m/%Y %H:%M') if d else '—'

        sol = fus.idSolicitanteInterno
        nombre_sol = f"{sol.first_name} {sol.last_name}".strip() if sol else '—'
        if not nombre_sol:
            nombre_sol = sol.email if sol else '—'

        ACCION_LABELS = {
            'REGISTRO_FUS': 'Registro FUS', 'TURNAR_FUS': 'Turnar FUS',
            'ASIGNACION_ESTADO': 'Cambio de estado',
            'REGISTRO_RESPUESTA': 'Registro respuesta',
            'REGISTRO_ACCION': 'Registro acción', 'CONCLUSION_FUS': 'Conclusión FUS',
            'INICIO_SESION': 'Inicio sesión', 'CIERRE_SESION': 'Cierre sesión',
            'RESTABLECER_CONTRASENA': 'Restablecer contraseña',
            'ELIMINACION': 'Eliminación',
        }

        elements = []

        # ── Encabezado ──
        hdr_data = [[
            Paragraph('FORMATO ÚNICO DE SOLICITUD', st_titulo),
            Paragraph(f'Folio: {fus.folio}', st_folio),
        ]]
        hdr_table = Table(hdr_data, colWidths=[11*cm, W - 11*cm])
        hdr_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'BOTTOM'),
            ('ALIGN',  (1,0), (1,0),   'RIGHT'),
        ]))
        elements.append(hdr_table)
        elements.append(HRFlowable(width='100%', thickness=2, color=VERDE, spaceAfter=10))

        def seccion(titulo):
            t = Table([[Paragraph(titulo, st_sec)]], colWidths=[W])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,-1), VERDE),
                ('TOPPADDING',    (0,0), (-1,-1), 4),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ]))
            return t

        def fila(lbl, val):
            return [Paragraph(lbl, st_lbl), Paragraph(str(val) if val else '—', st_val)]

        # ── Datos generales ──
        elements.append(seccion('DATOS GENERALES'))
        elements.append(Spacer(1, 4))
        datos = [
            fila('Fecha y hora',      fmt(fus.fechaHora)),
            fila('Solicitante',       nombre_sol),
            fila('Medio de recepción', fus.idMedioRecepcion.nombreMedio if fus.idMedioRecepcion else '—'),
            fila('Especificación',    fus.medioEspecificacion or '—'),
            fila('Prioridad',         fus.prioridad or '—'),
            fila('Estatus',           fus.estatusParticular_id),
        ]
        dt = Table(datos, colWidths=[4*cm, W - 4*cm])
        dt.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
            ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
            ('TOPPADDING',     (0,0), (-1,-1), 4),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 4),
            ('LEFTPADDING',    (0,0), (-1,-1), 6),
            ('RIGHTPADDING',   (0,0), (-1,-1), 6),
        ]))
        elements += [dt, Spacer(1, 8)]

        # ── Descripción ──
        elements.append(seccion('DESCRIPCIÓN DE LA SOLICITUD'))
        elements.append(Spacer(1, 4))
        desc_data = [
            fila('Descripción', fus.descripcion),
            fila('Contexto',    fus.contexto or '—'),
        ]
        dt2 = Table(desc_data, colWidths=[4*cm, W - 4*cm])
        dt2.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
            ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
            ('TOPPADDING',     (0,0), (-1,-1), 6),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 6),
            ('LEFTPADDING',    (0,0), (-1,-1), 6),
            ('RIGHTPADDING',   (0,0), (-1,-1), 6),
            ('VALIGN',         (0,0), (-1,-1), 'TOP'),
        ]))
        elements += [dt2, Spacer(1, 8)]

        # ── Solicitante externo ──
        if fus.nombreExterno or fus.correoExterno or fus.telefonoExterno:
            elements.append(seccion('SOLICITANTE EXTERNO'))
            elements.append(Spacer(1, 4))
            ext_data = [
                fila('Nombre',    fus.nombreExterno),
                fila('Correo',    fus.correoExterno),
                fila('Teléfono',  fus.telefonoExterno),
            ]
            dt3 = Table(ext_data, colWidths=[4*cm, W - 4*cm])
            dt3.setStyle(TableStyle([
                ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
                ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
                ('TOPPADDING',     (0,0), (-1,-1), 4),
                ('BOTTOMPADDING',  (0,0), (-1,-1), 4),
                ('LEFTPADDING',    (0,0), (-1,-1), 6),
                ('RIGHTPADDING',   (0,0), (-1,-1), 6),
            ]))
            elements += [dt3, Spacer(1, 8)]

        # ── Historial ──
        if bitacora.exists():
            elements.append(seccion('HISTORIAL DE ACCIONES'))
            elements.append(Spacer(1, 4))
            h_data = [['Fecha y hora', 'Usuario', 'Acción', 'Estado ant.', 'Estado nuevo', 'Observaciones']]
            for b in bitacora:
                h_data.append([
                    Paragraph(fmt(b.fechaHora), st_bita),
                    Paragraph(b.usuario or '—', st_bita),
                    Paragraph(ACCION_LABELS.get(b.accion, b.accion), st_bita),
                    Paragraph(b.estadoAnterior or '—', st_bita),
                    Paragraph(b.estadoNuevo    or '—', st_bita),
                    Paragraph(b.observaciones  or '—', st_bita),
                ])
            ht = Table(h_data, colWidths=[3.2*cm, 3.5*cm, 2.8*cm, 2*cm, 2*cm, W - 13.5*cm], repeatRows=1)
            ht.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,0),  VERDE),
                ('TEXTCOLOR',     (0,0), (-1,0),  colors.white),
                ('FONTNAME',      (0,0), (-1,0),  'Helvetica-Bold'),
                ('FONTSIZE',      (0,0), (-1,0),  7),
                ('ROWBACKGROUNDS',(0,1), (-1,-1),  [colors.white, CLARO]),
                ('GRID',          (0,0), (-1,-1),  0.3, BORDE),
                ('VALIGN',        (0,0), (-1,-1),  'TOP'),
                ('TOPPADDING',    (0,0), (-1,-1),  3),
                ('BOTTOMPADDING', (0,0), (-1,-1),  3),
                ('LEFTPADDING',   (0,0), (-1,-1),  4),
                ('RIGHTPADDING',  (0,0), (-1,-1),  4),
            ]))
            elements.append(ht)

        # ── Pie ──
        elements.append(Spacer(1, 12))
        elements.append(HRFlowable(width='100%', thickness=0.5, color=BORDE))
        pie = ParagraphStyle('pie', fontName='Helvetica', fontSize=7,
                             textColor=colors.HexColor('#888888'), spaceBefore=4)
        from datetime import datetime, timezone
        now_str = datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')
        elements.append(Paragraph(
            f'Agencia Nacional de Aduanas de México — Sistema de Control de Solicitudes — Generado: {now_str}',
            pie
        ))

        doc.build(elements)
        buf.seek(0)
        resp = HttpResponse(buf, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="FUS_{folio}.pdf"'
        return resp
