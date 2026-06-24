from django.urls import path
from .views import MedioRecepcionListView, PrioridadCriterioListView

urlpatterns = [
    path('medios/',      MedioRecepcionListView.as_view(),    name='medios-list'),
    path('prioridades/', PrioridadCriterioListView.as_view(), name='prioridades-list'),
]
