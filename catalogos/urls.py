from django.urls import path
from .views import MedioRecepcionListView, PrioridadCriterioListView, EstatusListView

urlpatterns = [
    path('medios/',      MedioRecepcionListView.as_view(),    name='medios-list'),
    path('prioridades/', PrioridadCriterioListView.as_view(), name='prioridades-list'),
    path('estatus/',     EstatusListView.as_view(),           name='estatus-list'),
]
