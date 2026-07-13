import hashlib
import json
import os
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from autenticacion.models import CorreoAutorizado
from catalogos.models import MedioRecepcion
from ..models import FUS, Evidencia, Turnado
from ..serializers import FUSSerializer, TurnadoActividadSerializer
from ..utils import resolver_nombre
from .helpers import _rol, _log, _ROL_FOLIO

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


def _guardar_evidencias(fus, request, user):
    """Valida y guarda los archivos de 'evidencias' del request para un FUS.
    Devuelve una Response de error si algo falla, o None si todo salió bien."""
    from django.conf import settings

    archivos = request.FILES.getlist('evidencias')
    if not archivos:
        return None

    total_size = sum(a.size for a in archivos)
    if total_size > MAX_TOTAL_SIZE:
        return Response({'detail': 'El total de archivos supera 30 MB.'}, status=status.HTTP_400_BAD_REQUEST)
    for archivo in archivos:
        err = _validar_archivo(archivo)
        if err:
            return Response({'detail': err}, status=status.HTTP_400_BAD_REQUEST)

    try:
        comentarios_lista = json.loads(request.data.get('comentariosEvidencias') or '[]')
    except (ValueError, TypeError):
        comentarios_lista = []

    for i, archivo in enumerate(archivos):
        sha = _sha256(archivo)
        nombre_seguro = os.path.basename(archivo.name)
        nombre_fisico = f"{uuid.uuid4().hex}_{nombre_seguro}"
        ruta_rel = f"evidencias/{fus.pk}/{nombre_fisico}"
        ruta_abs = os.path.join(settings.MEDIA_ROOT, ruta_rel)
        os.makedirs(os.path.dirname(ruta_abs), exist_ok=True)
        with open(ruta_abs, 'wb') as dest:
            for chunk in archivo.chunks():
                dest.write(chunk)
        comentario = comentarios_lista[i].strip() if i < len(comentarios_lista) and comentarios_lista[i] else None
        Evidencia.objects.create(
            idFus=fus,
            nombreArchivo=nombre_seguro,
            rutaArchivo=ruta_rel,
            tipoMime=archivo.content_type,
            hashSha256=sha,
            comentarios=comentario,
            idUsuarioRegistra=user.id,
        )
    return None


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
            emails_nombre = list(CorreoAutorizado.objects.filter(nombre__icontains=search).values_list('email', flat=True))
            qs = qs.filter(
                Q(folio__icontains=search) |
                Q(descripcion__icontains=search) |
                Q(contexto__icontains=search) |
                Q(medioEspecificacion__icontains=search) |
                Q(criterios__icontains=search) |
                Q(nombreExterno__icontains=search) |
                Q(telefonoExterno__icontains=search) |
                Q(correoExterno__icontains=search) |
                Q(idMedioRecepcion__nombreMedio__icontains=search) |
                Q(idSolicitanteInterno__email__icontains=search) |
                Q(idSolicitanteInterno__email__in=emails_nombre) |
                Q(evidencias__nombreArchivo__icontains=search) |
                Q(evidencias__comentarios__icontains=search) |
                Q(turnados__solicitudTexto__icontains=search) |
                Q(turnados__idMedio__nombreMedio__icontains=search) |
                Q(turnados__idRemitente__email__icontains=search) |
                Q(turnados__idRemitente__email__in=emails_nombre) |
                Q(turnados__idDestinatario__email__icontains=search) |
                Q(turnados__idDestinatario__email__in=emails_nombre) |
                Q(turnados__seguimientos__descripcionActividad__icontains=search) |
                Q(turnados__seguimientos__accionTexto__icontains=search)
            ).distinct()

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

        medio_id = data.get('idMedioRecepcion')
        medio    = get_object_or_404(MedioRecepcion, pk=medio_id) if medio_id else None

        nombre_ext = data.get('nombreExterno', '').strip() or None
        tel_ext    = data.get('telefonoExterno', '').strip() or None
        correo_ext = data.get('correoExterno', '').strip() or None

        from django.db import IntegrityError

        fus = None
        for intento in range(3):
            folio = _generar_folio(rol, year)
            try:
                fus = FUS.objects.create(
                    folio=folio,
                    idSolicitanteInterno=user,
                    fechaHora=now,
                    descripcion=data.get('descripcion', ''),
                    contexto=data.get('contexto', ''),
                    idMedioRecepcion=medio,
                    medioEspecificacion=data.get('medioEspecificacion', ''),
                    prioridad=data.get('prioridad') or None,
                    criterios=data.get('criterios') or None,
                    nombreExterno=nombre_ext,
                    telefonoExterno=tel_ext,
                    correoExterno=correo_ext,
                    estatusParticular_id='Registrado',
                    idUsuarioRegistra=user.id,
                    fechaLimite=data.get('fechaLimite') or None,
                )
                break
            except IntegrityError:
                if intento == 2:
                    raise
                continue

        err_resp = _guardar_evidencias(fus, request, user)
        if err_resp:
            fus.delete()
            return err_resp

        _log(usuario=user.email, rol=rol, accion='REGISTRO_FUS',
             ip=ip, folio=folio, estado_nuevo='Registrado')

        return Response(FUSSerializer(fus).data, status=status.HTTP_201_CREATED)


class FUSDetailView(APIView):
    """GET / PATCH — ver o editar un FUS individual (ROL1). Solo editable en estatus 'Registrado'."""
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser, JSONParser]

    def get(self, request, pk):
        if _rol(request.user) != 'ROL1':
            return Response({'detail': 'No autorizado.'}, status=403)
        fus = get_object_or_404(
            FUS.objects.select_related('idSolicitanteInterno', 'idMedioRecepcion').prefetch_related('evidencias'),
            pk=pk, activo=1, idSolicitanteInterno=request.user,
        )
        return Response(FUSSerializer(fus).data)

    def patch(self, request, pk):
        user = request.user
        rol  = _rol(user)
        if rol != 'ROL1':
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(FUS, pk=pk, activo=1, idSolicitanteInterno=user)
        if fus.estatusParticular_id != 'Registrado':
            return Response(
                {'detail': 'Solo se puede editar una solicitud en estatus "Registrado".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data
        if 'idMedioRecepcion' in data:
            medio_id = data.get('idMedioRecepcion')
            fus.idMedioRecepcion = get_object_or_404(MedioRecepcion, pk=medio_id) if medio_id else None
        if 'descripcion' in data:         fus.descripcion = data.get('descripcion', '')
        if 'contexto' in data:            fus.contexto = data.get('contexto', '')
        if 'medioEspecificacion' in data:  fus.medioEspecificacion = data.get('medioEspecificacion', '')
        if 'prioridad' in data:           fus.prioridad = data.get('prioridad') or None
        if 'criterios' in data:           fus.criterios = data.get('criterios') or None
        if 'nombreExterno' in data:       fus.nombreExterno = data.get('nombreExterno', '').strip() or None
        if 'telefonoExterno' in data:     fus.telefonoExterno = data.get('telefonoExterno', '').strip() or None
        if 'correoExterno' in data:       fus.correoExterno = data.get('correoExterno', '').strip() or None
        if 'fechaLimite' in data:         fus.fechaLimite = data.get('fechaLimite') or None
        fus.idUsuarioModifica = user.id
        fus.save()

        err_resp = _guardar_evidencias(fus, request, user)
        if err_resp:
            return err_resp

        _log(usuario=user.email, rol=rol, accion='REGISTRO_FUS',
             ip=request.META.get('REMOTE_ADDR'), folio=fus.folio, obs='Edición de solicitud')

        return Response(FUSSerializer(fus).data)


class FUSDetalleAuditoriaView(APIView):
    """Detalle de auditoría de un FUS por folio, para el modal de Bitácora (ROL1)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, folio):
        if _rol(request.user) != 'ROL1':
            return Response({'detail': 'No autorizado.'}, status=403)

        fus = get_object_or_404(
            FUS.objects.select_related('idSolicitanteInterno', 'idMedioRecepcion', 'estatusParticular'),
            folio=folio, activo=1,
        )

        turnados = Turnado.objects.filter(idFus=fus).select_related(
            'idDestinatario'
        ).prefetch_related('seguimientos').order_by('fechaHoraTurnado')

        seguimientos = []
        estatus_titular = None
        for t in turnados:
            estatus_titular = t.estatusTitular_id
            autor = (t.idDestinatario.first_name or t.idDestinatario.email) if t.idDestinatario else None
            for s in t.seguimientos.all():
                if not s.activo:
                    continue
                seguimientos.append({
                    'fecha': s.fechaActividad,
                    'autor': autor,
                    'texto': s.descripcionActividad,
                })

        sol = fus.idSolicitanteInterno
        return Response({
            'folio': fus.folio,
            'descripcion': fus.descripcion,
            'contexto': fus.contexto,
            'medioRecepcion': fus.idMedioRecepcion.nombreMedio if fus.idMedioRecepcion else None,
            'prioridad': fus.prioridad,
            'criterios': fus.criterios,
            'nombreExterno': fus.nombreExterno,
            'telefonoExterno': fus.telefonoExterno,
            'correoExterno': fus.correoExterno,
            'estatusParticular': fus.estatusParticular_id,
            'estatusTitular': estatus_titular,
            'fechaRegistro': fus.fechaRegistro,
            'idSolicitanteInterno': {
                'nombre': resolver_nombre(sol) if sol else None,
                'email': sol.email if sol else None,
            },
            'evidencias': [{'nombreArchivo': e.nombreArchivo} for e in fus.evidencias.filter(activo=1)],
            'seguimientos': seguimientos,
        })


# ── Descargar evidencia (archivo adjunto de un FUS) ───────────────────────────

class DescargarEvidenciaView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, evidencia_id):
        evidencia = get_object_or_404(Evidencia, pk=evidencia_id, activo=1)
        fus = evidencia.idFus
        rol = _rol(request.user)
        if rol == 'ROL1' and fus.idSolicitanteInterno_id != request.user.id:
            raise Http404
        if rol == 'ROL2':
            es_destinatario = Turnado.objects.filter(idFus=fus, idDestinatario=request.user, activo=1).exists()
            if not es_destinatario:
                raise Http404
        ruta = os.path.join(settings.MEDIA_ROOT, evidencia.rutaArchivo)
        if not os.path.exists(ruta):
            raise Http404
        return FileResponse(open(ruta, 'rb'), as_attachment=True, filename=evidencia.nombreArchivo)


# ── Descargar FUS individual (PDF) ────────────────────────────────────────────

def generar_pdf_fus(fus, incluir_imagenes=False):
    """Construye el PDF de un FUS (usado tanto para la descarga directa como
    para el adjunto en las notificaciones por correo). Devuelve los bytes."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, Image as RLImage, PageBreak, KeepTogether,
    )
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    import io

    evidencias = [e for e in fus.evidencias.all() if e.activo]
    turnados = [t for t in fus.turnados.all() if t.activo]

    LETTERHEAD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'assets', 'membretada.png')

    def _membrete(canvas_, doc_):
        canvas_.saveState()
        if os.path.exists(LETTERHEAD_PATH):
            canvas_.drawImage(
                LETTERHEAD_PATH, 0, 0,
                width=letter[0], height=letter[1],
                mask='auto', preserveAspectRatio=False,
            )
        canvas_.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=3.3*cm, bottomMargin=2.8*cm)
    W = letter[0] - 4*cm  # ancho útil

    VERDE    = colors.black
    AMARILLO = colors.HexColor('#FFFF00')
    CLARO    = colors.white
    BORDE    = colors.black

    styles = getSampleStyleSheet()

    st_titulo = ParagraphStyle('titulo', fontName='Helvetica-Bold', fontSize=16,
                               textColor=colors.black, spaceAfter=2)
    st_folio  = ParagraphStyle('folio',  fontName='Helvetica-Bold', fontSize=11,
                               textColor=colors.black, spaceBefore=6, spaceAfter=8)
    st_sec    = ParagraphStyle('sec',    fontName='Helvetica-Bold', fontSize=9,
                               textColor=colors.black, spaceAfter=0)
    st_lbl    = ParagraphStyle('lbl',    fontName='Helvetica-Bold', fontSize=8,
                               textColor=colors.black)
    st_val    = ParagraphStyle('val',    fontName='Helvetica',      fontSize=8,
                               textColor=colors.black, leading=11)

    fmt = lambda d: d.strftime('%d/%m/%Y %H:%M') if d else '—'

    sol = fus.idSolicitanteInterno
    nombre_sol = resolver_nombre(sol) if sol else '—'

    elements = []

    # ── Encabezado ──
    elements.append(Paragraph('FORMATO ÚNICO DE SOLICITUD', st_titulo))
    elements.append(Paragraph(
        f'Folio: {fus.folio} &nbsp;|&nbsp; Estatus: {fus.estatusParticular_id}',
        st_folio,
    ))
    elements.append(HRFlowable(width='100%', thickness=2, color=VERDE, spaceAfter=10))

    def seccion(titulo):
        t = Table([[Paragraph(titulo, st_sec)]], colWidths=[W])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), AMARILLO),
            ('TOPPADDING',    (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ]))
        return t

    def fila(lbl, val):
        return [Paragraph(lbl, st_lbl), Paragraph(str(val) if val else '—', st_val)]

    # ── Datos generales ──
    datos = [
        fila('Fecha y hora',        fmt(fus.fechaHora)),
        fila('Medio de recepción',  fus.idMedioRecepcion.nombreMedio if fus.idMedioRecepcion else '—'),
        fila('Solicitante interno', nombre_sol),
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
    elements.append(KeepTogether([seccion('DATOS GENERALES'), Spacer(1, 4), dt]))
    elements.append(Spacer(1, 8))

    # ── Descripción ──
    desc_data = [
        fila('Descripción', fus.descripcion),
        fila('Datos o antecedentes de contexto de la solicitud', fus.contexto or '—'),
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
    elements.append(KeepTogether([seccion('DESCRIPCIÓN DE LA SOLICITUD'), Spacer(1, 4), dt2]))
    elements.append(Spacer(1, 8))

    # ── Solicitante externo ──
    if fus.nombreExterno or fus.correoExterno or fus.telefonoExterno:
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
        elements.append(KeepTogether([seccion('SOLICITANTE EXTERNO'), Spacer(1, 4), dt3]))
        elements.append(Spacer(1, 8))

    # ── Evidencia (solo nombres de archivo; las imágenes van al final si se solicitaron) ──
    if evidencias:
        ev_rows = []
        for ev in evidencias:
            texto = ev.nombreArchivo or '—'
            if ev.comentarios:
                texto += f' — {ev.comentarios}'
            ev_rows.append([Paragraph(texto, st_val)])
        evt = Table(ev_rows, colWidths=[W])
        evt.setStyle(TableStyle([
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
            ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
            ('TOPPADDING',     (0,0), (-1,-1), 5),
            ('BOTTOMPADDING',  (0,0), (-1,-1), 5),
            ('LEFTPADDING',    (0,0), (-1,-1), 8),
        ]))
        elements.append(KeepTogether([seccion('EVIDENCIA'), Spacer(1, 4), evt]))
    else:
        elements.append(KeepTogether([seccion('EVIDENCIA'), Spacer(1, 4), Paragraph('—', st_val)]))
    elements.append(Spacer(1, 8))

    # ── Prioridad ──
    prioridad_bloque = [seccion('PRIORIDAD'), Spacer(1, 4), Paragraph(f'<b>{fus.prioridad or "—"}</b>', st_val)]
    if fus.criterios:
        prioridad_bloque.append(Spacer(1, 2))
        for crit in [c.strip() for c in fus.criterios.split('|') if c.strip()]:
            prioridad_bloque.append(Paragraph(f'• {crit}', st_val))
    elements.append(KeepTogether(prioridad_bloque))
    elements.append(Spacer(1, 8))

    # ── Se turnó ──
    if turnados:
        for i, t in enumerate(turnados):
            dest_nombre = resolver_nombre(t.idDestinatario) if t.idDestinatario else '—'
            turno_data = [
                fila('Nombre',             dest_nombre),
                fila('Medio de envío',     t.idMedio.nombreMedio if t.idMedio else '—'),
                fila('Fecha y hora',       fmt(t.fechaHoraTurnado)),
                fila('Texto de la solicitud', t.solicitudTexto or '—'),
            ]
            tnt = Table(turno_data, colWidths=[4*cm, W - 4*cm])
            tnt.setStyle(TableStyle([
                ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
                ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
                ('TOPPADDING',     (0,0), (-1,-1), 4),
                ('BOTTOMPADDING',  (0,0), (-1,-1), 4),
                ('LEFTPADDING',    (0,0), (-1,-1), 6),
                ('RIGHTPADDING',   (0,0), (-1,-1), 6),
                ('VALIGN',         (0,0), (-1,-1), 'TOP'),
            ]))
            bloque = [seccion('SE TURNÓ'), Spacer(1, 4), tnt] if i == 0 else [tnt]
            elements.append(KeepTogether(bloque))
            elements.append(Spacer(1, 6))

    # ── Respuesta y seguimiento ──
    turnados_con_seguimiento = [
        (t, [s for s in t.seguimientos.all() if s.activo]) for t in turnados
    ]
    turnados_con_seguimiento = [(t, segs) for t, segs in turnados_con_seguimiento if segs]

    if turnados:
        if turnados_con_seguimiento:
            for i, (t, segs) in enumerate(turnados_con_seguimiento):
                dest_nombre = resolver_nombre(t.idDestinatario) if t.idDestinatario else '—'
                seg_rows = []
                for s in segs:
                    fecha_str = s.fechaActividad.strftime('%d/%m/%Y') if s.fechaActividad else '—'
                    texto = s.descripcionActividad or '—'
                    if s.accionTexto:
                        texto += f'<br/>→ {s.accionTexto}'
                    seg_rows.append([Paragraph(fecha_str, st_val), Paragraph(texto, st_val)])
                segt = Table(seg_rows, colWidths=[3*cm, W - 3*cm])
                segt.setStyle(TableStyle([
                    ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.white, CLARO]),
                    ('GRID',           (0,0), (-1,-1), 0.3, BORDE),
                    ('TOPPADDING',     (0,0), (-1,-1), 4),
                    ('BOTTOMPADDING',  (0,0), (-1,-1), 4),
                    ('LEFTPADDING',    (0,0), (-1,-1), 6),
                    ('RIGHTPADDING',   (0,0), (-1,-1), 6),
                    ('VALIGN',         (0,0), (-1,-1), 'TOP'),
                ]))
                bloque = [Paragraph(dest_nombre, st_lbl), Spacer(1, 2), segt]
                if i == 0:
                    bloque = [seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4)] + bloque
                elements.append(KeepTogether(bloque))
                elements.append(Spacer(1, 8))
        else:
            elements.append(KeepTogether([
                seccion('RESPUESTA Y SEGUIMIENTO'), Spacer(1, 4),
                Paragraph('Pendiente de respuesta del titular.', st_val),
            ]))
            elements.append(Spacer(1, 8))

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

    # ── Anexo de imágenes de evidencia (hoja nueva, al final) ──
    if incluir_imagenes:
        imagenes = [e for e in evidencias if (e.tipoMime or '').startswith('image/')]
        rutas_validas = []
        for ev in imagenes:
            ruta_abs = os.path.join(settings.MEDIA_ROOT, ev.rutaArchivo or '')
            if ev.rutaArchivo and os.path.exists(ruta_abs):
                rutas_validas.append((ev, ruta_abs))

        if rutas_validas:
            elements.append(PageBreak())
            elements.append(Paragraph('ANEXO — IMÁGENES DE EVIDENCIA', st_titulo))
            elements.append(HRFlowable(width='100%', thickness=2, color=VERDE, spaceAfter=12))
            max_w, max_h = W, 20*cm
            for ev, ruta_abs in rutas_validas:
                elements.append(Paragraph(ev.nombreArchivo or '—', st_lbl))
                elements.append(Spacer(1, 4))
                try:
                    img = RLImage(ruta_abs)
                    ratio = min(max_w / img.imageWidth, max_h / img.imageHeight, 1)
                    img.drawWidth  = img.imageWidth * ratio
                    img.drawHeight = img.imageHeight * ratio
                    elements.append(img)
                except Exception:
                    elements.append(Paragraph('(No se pudo cargar la imagen)', st_val))
                elements.append(Spacer(1, 16))

    doc.build(elements, onFirstPage=_membrete, onLaterPages=_membrete)
    return buf.getvalue()


class DescargarFUSPDFView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, folio):
        from django.http import HttpResponse
        try:
            fus = FUS.objects.select_related(
                'idSolicitanteInterno', 'idMedioRecepcion', 'estatusParticular'
            ).prefetch_related(
                'evidencias', 'turnados__idDestinatario', 'turnados__idMedio', 'turnados__seguimientos'
            ).get(folio=folio, activo=1)
        except FUS.DoesNotExist:
            from rest_framework.response import Response
            return Response({'detail': 'FUS no encontrado.'}, status=404)

        incluir_imagenes = request.query_params.get('imagenes') == '1'
        pdf_bytes = generar_pdf_fus(fus, incluir_imagenes=incluir_imagenes)
        resp = HttpResponse(pdf_bytes, content_type='application/pdf')
        nombre = fus.folio.replace('/', '-')
        resp['Content-Disposition'] = f'attachment; filename="FUS_{nombre}.pdf"'
        return resp
