from django.urls import path

from .views import AdminResumenAnaliticaView, EventosUsoView


urlpatterns = [
    path('eventos/', EventosUsoView.as_view(), name='analitica-eventos'),
    path('admin/resumen/', AdminResumenAnaliticaView.as_view(), name='analitica-admin-resumen'),
]
