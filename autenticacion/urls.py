from django.urls import path
from .views import (
    LoginView, LogoutView, UsuariosROL2View,
    VerificarCorreoView, VerificarOTPView,
    EstablecerContrasenaView, ReenviarOTPView,
    RecuperarContrasenaView, RestablecerContrasenaView,
    CorreoAutorizadoListView, CorreoAutorizadoDetailView,
    CookieTokenRefreshView,
)

urlpatterns = [
    path('login/',                  LoginView.as_view(),               name='auth-login'),
    path('logout/',                 LogoutView.as_view(),               name='auth-logout'),
    path('token/refresh/',          CookieTokenRefreshView.as_view(),   name='token-refresh'),
    path('usuarios-rol2/',          UsuariosROL2View.as_view(),         name='usuarios-rol2'),
    path('verificar-correo/',       VerificarCorreoView.as_view(),      name='verificar-correo'),
    path('verificar-otp/',          VerificarOTPView.as_view(),         name='verificar-otp'),
    path('establecer-contrasena/',  EstablecerContrasenaView.as_view(), name='establecer-contrasena'),
    path('reenviar-otp/',           ReenviarOTPView.as_view(),          name='reenviar-otp'),
    path('recuperar-contrasena/',   RecuperarContrasenaView.as_view(),     name='recuperar-contrasena'),
    path('restablecer-contrasena/', RestablecerContrasenaView.as_view(),   name='restablecer-contrasena'),
    path('correos-autorizados/',    CorreoAutorizadoListView.as_view(),    name='correos-autorizados'),
    path('correos-autorizados/<int:pk>/', CorreoAutorizadoDetailView.as_view(), name='correo-autorizado-detail'),
]
