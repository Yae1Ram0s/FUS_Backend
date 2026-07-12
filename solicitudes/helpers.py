from autenticacion.models import CorreoAutorizado


def _resolver_unidad_administrativa(user):
    autorizado = CorreoAutorizado.objects.select_related('unidadAdministrativa').filter(email=user.email).first()
    if autorizado and autorizado.unidadAdministrativa_id:
        return autorizado.unidadAdministrativa.unidadAdministrativa
    return 'Sin unidad asignada'
