from django.db.models import Q


ESTADOS_TEMPORALES = {'Vencido', 'PorVencer'}


def estados_visibles_bitacora(registro, rol_visor):
    """Devuelve la transición desde la perspectiva del usuario que consulta.

    El FUS y el Turnado usan vocabularios distintos. Los registros generados
    por ROL2 conservan históricamente el estado general del FUS, por lo que se
    traducen aquí al flujo del titular sin modificar los datos de auditoría.
    """
    anterior = registro.estadoAnterior
    nuevo = registro.estadoNuevo

    if rol_visor != 'ROL2':
        return anterior, nuevo

    if registro.accion == 'REAPERTURA_FUS':
        return 'Rechazado', 'En_seguimiento'

    if registro.accion == 'ASIGNACION_ESTADO':
        if anterior == 'En_seguimiento':
            return 'En_seguimiento', 'Pendiente_validacion'
        return ('Rechazado' if anterior == 'Rechazado' else 'Recibido'), 'En_seguimiento'

    if registro.accion in ('REGISTRO_RESPUESTA', 'REGISTRO_ACCION'):
        return anterior, 'En_seguimiento'

    return anterior, nuevo


def condicion_estatus_rol2(estatus):
    """Condición equivalente a ``estados_visibles_bitacora`` para consultas."""
    if estatus == 'En_seguimiento':
        return (
            Q(accion__in=['REGISTRO_RESPUESTA', 'REGISTRO_ACCION', 'REAPERTURA_FUS'])
            | (Q(accion='ASIGNACION_ESTADO') & ~Q(estadoAnterior='En_seguimiento'))
        )
    if estatus == 'Pendiente_validacion':
        return Q(accion='ASIGNACION_ESTADO', estadoAnterior='En_seguimiento')
    if estatus == 'Concluido':
        return Q(estadoNuevo='Concluido')
    if estatus == 'Rechazado':
        return Q(estadoNuevo='Rechazado')
    if estatus == 'Recibido':
        # La recepción no genera por sí sola un registro del propio titular;
        # se conserva el filtro por consistencia con su flujo, sin mezclar el
        # evento TURNAR_FUS de ROL1 ni movimientos de otros destinatarios.
        return Q(pk__in=[])
    return Q(pk__in=[])
