from django.urls import path
from .views import (
    FUSListCreateView,
    TurnarFUSView,
    ConcluirTurnadoView,
    MisTurnadosView,
    SeguimientoListCreateView,
    SeguimientoDeleteView,
    AccionListCreateView,
    AccionUpdateDeleteView,
    NotificacionListView,
    NotificacionMarcarLeidaView,
    NotificacionMarcarTodasView,
)

urlpatterns = [
    # FUS
    path('fus/',                               FUSListCreateView.as_view(),      name='fus-list-create'),
    path('fus/<int:pk>/turnar/',               TurnarFUSView.as_view(),          name='fus-turnar'),

    # Turnados ROL2
    path('turnados/mis-turnados/',             MisTurnadosView.as_view(),        name='mis-turnados'),
    path('turnados/<int:pk>/concluir/',        ConcluirTurnadoView.as_view(),    name='turnado-concluir'),

    # Seguimientos
    path('turnados/<int:turnado_id>/seguimientos/', SeguimientoListCreateView.as_view(), name='seguimientos'),
    path('seguimientos/<int:pk>/',                  SeguimientoDeleteView.as_view(),     name='seguimiento-delete'),

    # Acciones
    path('turnados/<int:turnado_id>/acciones/', AccionListCreateView.as_view(),   name='acciones'),
    path('acciones/<int:pk>/',                  AccionUpdateDeleteView.as_view(), name='accion-detail'),

    # Notificaciones (leer-todas debe ir antes que <uuid:pk>)
    path('notificaciones/',                         NotificacionListView.as_view(),        name='notificaciones'),
    path('notificaciones/leer-todas/',              NotificacionMarcarTodasView.as_view(), name='notificaciones-leer-todas'),
    path('notificaciones/<uuid:pk>/leer/',          NotificacionMarcarLeidaView.as_view(), name='notificacion-leer'),
]
