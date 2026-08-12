from django.urls import path
from .views import (
    LoginView, LogoutView, UsuariosROL2View,
    VerificarCorreoView, VerificarOTPView,
    EstablecerContrasenaView, ReenviarOTPView,
    RecuperarContrasenaView, RestablecerContrasenaView,
    CorreoAutorizadoListView, CorreoAutorizadoDetailView,
    CookieTokenRefreshView, CambiarContrasenaObligatoriaView,
)
from .admin_views import (
    AdminResumenView, AdminUsuariosView, AdminUsuarioDetalleView,
    AdminUsuarioAccionView, AdminRestablecerContrasenaView,
    AdminSaludView, AdminSaludHistorialView,
    AdminAuditoriaView, AdminAuditoriaSerieView, AdminMetricasView,
    AdminOTPView,
)


def accion_admin(nombre):
    return type(f'Admin{nombre.title()}View', (AdminUsuarioAccionView,), {'accion': nombre})

urlpatterns = [
    path('login/',                  LoginView.as_view(),               name='auth-login'),
    path('logout/',                 LogoutView.as_view(),               name='auth-logout'),
    path('token/refresh/',          CookieTokenRefreshView.as_view(),   name='token-refresh'),
    path('cambiar-contrasena-obligatoria/', CambiarContrasenaObligatoriaView.as_view(), name='cambiar-contrasena-obligatoria'),
    path('usuarios-rol2/',          UsuariosROL2View.as_view(),         name='usuarios-rol2'),
    path('verificar-correo/',       VerificarCorreoView.as_view(),      name='verificar-correo'),
    path('verificar-otp/',          VerificarOTPView.as_view(),         name='verificar-otp'),
    path('establecer-contrasena/',  EstablecerContrasenaView.as_view(), name='establecer-contrasena'),
    path('reenviar-otp/',           ReenviarOTPView.as_view(),          name='reenviar-otp'),
    path('recuperar-contrasena/',   RecuperarContrasenaView.as_view(),     name='recuperar-contrasena'),
    path('restablecer-contrasena/', RestablecerContrasenaView.as_view(),   name='restablecer-contrasena'),
    path('correos-autorizados/',    CorreoAutorizadoListView.as_view(),    name='correos-autorizados'),
    path('correos-autorizados/<int:pk>/', CorreoAutorizadoDetailView.as_view(), name='correo-autorizado-detail'),
    path('admin/resumen/', AdminResumenView.as_view(), name='admin-resumen'),
    path('admin/metricas/', AdminMetricasView.as_view(), name='admin-metricas'),
    path('admin/usuarios/', AdminUsuariosView.as_view(), name='admin-usuarios'),
    path('admin/usuarios/<int:pk>/', AdminUsuarioDetalleView.as_view(), name='admin-usuario'),
    path('admin/usuarios/<int:pk>/activar/', accion_admin('activar').as_view(), name='admin-activar'),
    path('admin/usuarios/<int:pk>/desactivar/', accion_admin('desactivar').as_view(), name='admin-desactivar'),
    path('admin/usuarios/<int:pk>/desbloquear/', accion_admin('desbloquear').as_view(), name='admin-desbloquear'),
    path('admin/usuarios/<int:pk>/cerrar-sesiones/', accion_admin('cerrar_sesiones').as_view(), name='admin-cerrar-sesiones'),
    path('admin/usuarios/<int:pk>/restablecer-contrasena/', AdminRestablecerContrasenaView.as_view(), name='admin-restablecer'),
    path('admin/salud/', AdminSaludView.as_view(), name='admin-salud'),
    path('admin/otp/', AdminOTPView.as_view(), name='admin-otp'),
    path('admin/salud/historial/', AdminSaludHistorialView.as_view(), name='admin-salud-historial'),
    path('admin/auditoria/', AdminAuditoriaView.as_view(), name='admin-auditoria'),
    path('admin/auditoria/serie/', AdminAuditoriaSerieView.as_view(), name='admin-auditoria-serie'),
]
