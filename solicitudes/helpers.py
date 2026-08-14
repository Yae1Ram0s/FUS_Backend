from autenticacion.models import CorreoAutorizado


def _resolver_unidad_administrativa(user, mapa=None):
    if mapa is not None:
        entrada = mapa.get(user.email)
        return entrada['unidad'] if entrada else 'Sin unidad asignada'
    autorizado = CorreoAutorizado.objects.select_related(
        'unidadAdministrativa'
    ).filter(email=user.email).first()
    if autorizado and autorizado.unidadAdministrativa_id:
        return autorizado.unidadAdministrativa.unidadAdministrativa
    return 'Sin unidad asignada'


def mapa_correos_autorizados(emails):
    """Precomputa {email: {'nombre', 'unidad'}} en una sola consulta — evita
    que resolver_nombre()/_resolver_unidad_administrativa() (que sin `mapa`
    golpean la BD una vez por llamada, cada una) se disparen dos veces por
    cada usuario que serializa UserMiniSerializer/FUSSerializer. Mismo patrón
    que ya usan Bitácora y Reportes (nombres_map / _unidad_por_correo),
    aplicado aquí a los listados de FUS/Turnado — la fuente de N+1 más grande
    del sistema (una fila de Turnado puede resolver hasta ~6 usuarios)."""
    filas = CorreoAutorizado.objects.filter(email__in=emails).values(
        'email', 'nombre', 'unidadAdministrativa__unidadAdministrativa',
    )
    return {
        f['email']: {
            'nombre': f['nombre'],
            'unidad': f['unidadAdministrativa__unidadAdministrativa'] or 'Sin unidad asignada',
        }
        for f in filas
    }


def emails_de_fus(fus_iterable):
    """Recolecta los emails de todos los usuarios que FUSSerializer puede
    llegar a resolver por cada FUS (solicitante, comisionado, destinatarios
    de sus turnados activos), para construir mapa_correos_autorizados() en
    una sola consulta en vez de una por usuario.

    Asume que idSolicitanteInterno/idComisionado ya vienen con
    select_related y turnados__idDestinatario con prefetch_related en el
    queryset de origen — sin eso, recorrer estos atributos vuelve a disparar
    exactamente las consultas que este mapa busca evitar."""
    emails = set()
    for fus in fus_iterable:
        if fus.idSolicitanteInterno_id:
            emails.add(fus.idSolicitanteInterno.email)
        if fus.idComisionado_id:
            emails.add(fus.idComisionado.email)
        for turnado in fus.turnados.all():
            if turnado.activo and turnado.idDestinatario_id:
                emails.add(turnado.idDestinatario.email)
    return emails


def emails_de_turnados(turnados_iterable):
    """Igual que emails_de_fus, más remitente/destinatario del propio
    Turnado — usado por TurnadoSerializer, que anida un FUSSerializer
    completo (idFus) además de sus propios UserMiniSerializer."""
    turnados_iterable = list(turnados_iterable)
    emails = emails_de_fus(t.idFus for t in turnados_iterable if t.idFus_id)
    for turnado in turnados_iterable:
        if turnado.idRemitente_id:
            emails.add(turnado.idRemitente.email)
        if turnado.idDestinatario_id:
            emails.add(turnado.idDestinatario.email)
    return emails
