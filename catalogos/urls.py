from django.urls import path
from .views import MedioRecepcionListView, EstatusListView, UnidadAdministrativaListView

urlpatterns = [
    path('medios/',      MedioRecepcionListView.as_view(),    name='medios-list'),
    path('estatus/',     EstatusListView.as_view(),           name='estatus-list'),
    path('unidades-administrativas/', UnidadAdministrativaListView.as_view(), name='unidades-administrativas-list'),
]
