from django.urls import path
from .views import (
    FUSListCreateView,
    FUSDetailView,
    TurnarFUSView,
    FUSActividadView,
    FUSDetalleAuditoriaView,
    ConcluirTurnadoView,
    MisTurnadosView,
    SeguimientoListCreateView,
    SeguimientoDeleteView,
    NotificacionListView,
    NotificacionMarcarLeidaView,
    NotificacionMarcarTodasView,
    BitacoraListView,
    ExportarFUSExcelView,
    ExportarFUSPDFView,
    ExportarBitacoraExcelView,
    ExportarBitacoraPDFView,
    DescargarFUSPDFView,
    DescargarEvidenciaView,
    FUSTrazabilidadView,
    ActividadListCreateView,
    ActividadDetailView,
    FUSComisionadosDisponiblesView,
    ComisionarFUSView,
    MisFUSComisionadosView,
    SeguimientoComisionadoListCreateView,
    FinalizarSeguimientoView,
    AprobarFUSView,
    RechazarFUSView,
)

urlpatterns = [
    # FUS
    path('fus/',                               FUSListCreateView.as_view(),      name='fus-list-create'),
    path('fus/<int:pk>/',                      FUSDetailView.as_view(),          name='fus-detail'),
    path('fus/<int:pk>/turnar/',               TurnarFUSView.as_view(),          name='fus-turnar'),
    path('fus/<int:pk>/actividad/',            FUSActividadView.as_view(),       name='fus-actividad'),
    path('fus/detalle-auditoria/<path:folio>/', FUSDetalleAuditoriaView.as_view(), name='fus-detalle-auditoria'),
    path('fus/trazabilidad/<path:folio>/',      FUSTrazabilidadView.as_view(),     name='fus-trazabilidad'),

    # Turnados ROL2
    path('turnados/mis-turnados/',             MisTurnadosView.as_view(),        name='mis-turnados'),
    path('turnados/<int:pk>/concluir/',        ConcluirTurnadoView.as_view(),    name='turnado-concluir'),

    # Seguimientos
    path('turnados/<int:turnado_id>/seguimientos/', SeguimientoListCreateView.as_view(), name='seguimientos'),
    path('seguimientos/<int:pk>/',                  SeguimientoDeleteView.as_view(),     name='seguimiento-delete'),

    # Notificaciones (leer-todas debe ir antes que <uuid:pk>)
    path('notificaciones/',                         NotificacionListView.as_view(),        name='notificaciones'),
    path('notificaciones/leer-todas/',              NotificacionMarcarTodasView.as_view(), name='notificaciones-leer-todas'),
    path('notificaciones/<uuid:pk>/leer/',          NotificacionMarcarLeidaView.as_view(), name='notificacion-leer'),

    # Bitácora
    path('bitacora/',                          BitacoraListView.as_view(),          name='bitacora'),
    path('bitacora/exportar/excel/',           ExportarBitacoraExcelView.as_view(), name='bitacora-exportar-excel'),
    path('bitacora/exportar/pdf/',             ExportarBitacoraPDFView.as_view(),   name='bitacora-exportar-pdf'),

    # Exportar FUS (lista)
    path('fus/exportar/excel/',       ExportarFUSExcelView.as_view(),  name='fus-exportar-excel'),
    path('fus/exportar/pdf/',         ExportarFUSPDFView.as_view(),    name='fus-exportar-pdf'),

    # Descargar FUS individual (folio contiene slashes → path converter)
    path('fus/<path:folio>/pdf/',     DescargarFUSPDFView.as_view(),   name='fus-descargar-pdf'),

    # Descargar evidencia
    path('evidencias/<int:evidencia_id>/descargar/', DescargarEvidenciaView.as_view(), name='evidencia-descargar'),

    # Calendario de actividades
    path('actividades/',            ActividadListCreateView.as_view(), name='actividad-list-create'),
    path('actividades/<int:pk>/',   ActividadDetailView.as_view(),     name='actividad-detail'),

    # Comisionado (mis-comisionados debe ir antes que fus/<int:pk>/ para no ambigüedad de lectura)
    path('fus/mis-comisionados/',                  MisFUSComisionadosView.as_view(),          name='fus-mis-comisionados'),
    path('fus/<int:pk>/comisionados-disponibles/', FUSComisionadosDisponiblesView.as_view(),  name='fus-comisionados-disponibles'),
    path('fus/<int:pk>/comisionar/',               ComisionarFUSView.as_view(),               name='fus-comisionar'),
    path('fus/<int:pk>/seguimiento/',               SeguimientoComisionadoListCreateView.as_view(), name='fus-seguimiento-comisionado'),
    path('fus/<int:pk>/finalizar-seguimiento/',    FinalizarSeguimientoView.as_view(),        name='fus-finalizar-seguimiento'),
    path('fus/<int:pk>/aprobar/',                  AprobarFUSView.as_view(),                  name='fus-aprobar'),
    path('fus/<int:pk>/rechazar/',                 RechazarFUSView.as_view(),                 name='fus-rechazar'),
]
