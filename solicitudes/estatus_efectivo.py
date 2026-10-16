"""Estatus efectivo de un FUS para ROL1 — la regla única detrás de la tarjeta,
de los chips de Consultar FUS y de sus conteos.

Un FUS tiene dos estatus que pueden diferir: FUS.estatusParticular y, por cada
persona turnada, Turnado.estatusTitular (marcar atendido, rechazar o concluir
la parte de UNA persona solo toca su turnado). Para que cada FUS caiga en un
solo chip — y la suma de chips dé el total — se usa siempre el mismo criterio:

  * Con exactamente un turnado activo que ya no está en 'Recibido', manda el
    estatus de ese turnado (es "todo el FUS", no una parte).
  * En cualquier otro caso (sin turnados, varias personas, o única persona
    todavía en 'Recibido'), manda el estatus del FUS.

La versión en Python (`estatus_visual`) la usa FUSSerializer para la tarjeta;
la versión en SQL (`anotar_estatus_efectivo`) la usan el filtro y los conteos
de la bandeja. Deben decir siempre lo mismo (hay un test que lo comprueba).

Para ROL2 (Solicitudes turnadas) no hace falta: cada fila es SU turnado y el
estatus efectivo es siempre Turnado.estatusTitular. Lo que sí comparten ambos
roles son los helpers de abajo para el grupo "Plazo" (Vencido / Por vencer),
que cruza los estatus y se combina con ellos.
"""
from datetime import timedelta

from django.db.models import Case, CharField, Count, F, IntegerField, OuterRef, Q, Subquery, Value, When
from django.utils import timezone

from .models import Turnado

# Vencido / Por vencer son temporalidad, no estatus del trámite.
PLAZOS = ('Vencido', 'PorVencer')

# El catálogo PARTICULAR llama 'Atendido' al chip que ROL1 lee como "En
# seguimiento"; el turnado (flujo TITULAR) y el FUS recién comisionado lo
# llaman 'En_seguimiento'. Los tres son el mismo chip.
CHIP_DE_ESTATUS = {'En_seguimiento': 'Atendido'}


def clave_chip(estatus):
    return CHIP_DE_ESTATUS.get(estatus, estatus)


def separar_estatus_y_plazo(estatus_raw, plazo_raw, normalizar=lambda clave: clave):
    """Separa lo que pidió el frontend en (claves de chip de estatus, plazos).
    Vencido/PorVencer llegan en `plazo`, pero también se aceptan dentro del
    parámetro de estatus (enlaces viejos de los dashboards) para no romperlos.
    `normalizar` traduce alias de estatus (ver CHIP_DE_ESTATUS)."""
    pedidos = {c.strip() for c in f'{estatus_raw or ""},{plazo_raw or ""}'.split(',') if c.strip()}
    plazos = sorted(c for c in pedidos if c in PLAZOS)
    estatus = {normalizar(c) for c in pedidos if c not in PLAZOS}
    return estatus, plazos


def q_plazo(plazos, campo_fecha_limite, concluido):
    """Q() de Vencido/PorVencer (varios con OR) sobre `campo_fecha_limite`.
    Mide la fechaLimite sin importar en qué estatus del trámite esté el FUS —
    salvo lo que ya está concluido (`concluido`, un Q), donde el plazo deja
    de aplicar. Se combina con el estatus elegido (AND): un FUS rechazado
    también puede estar vencido. Sin plazos pedidos devuelve un Q() vacío."""
    if not plazos:
        return Q()
    ahora = timezone.now()
    q = Q()
    for plazo in plazos:
        if plazo == 'Vencido':
            q |= Q(**{f'{campo_fecha_limite}__lt': ahora})
        else:
            q |= Q(**{
                f'{campo_fecha_limite}__gte': ahora,
                f'{campo_fecha_limite}__lte': ahora + timedelta(hours=24),
            })
    return q & ~concluido


def estatus_visual(estatus_fus, estatus_turnados_activos):
    if len(estatus_turnados_activos) == 1 and estatus_turnados_activos[0] != 'Recibido':
        return estatus_turnados_activos[0]
    return estatus_fus


def debe_quedar_rechazado(estatus_fus, estatus_turnados_activos):
    """True si el FUS debe quedar 'Rechazado' a nivel FUS porque TODAS sus
    personas turnadas activas ya están rechazadas. Rechazar la parte de una
    persona (RechazarPersonaTurnadoView) solo toca su turnado; sin esto, con
    una sola persona el FUS conservaba su estatus anterior ('Atendido' o
    'Pendiente_validacion') mientras su turnado decía 'Rechazado', y la
    reapertura tras una nueva respuesta no sabía de qué estado salir."""
    return (
        bool(estatus_turnados_activos)
        and set(estatus_turnados_activos) == {'Rechazado'}
        and estatus_fus not in ('Rechazado', 'Concluido')
    )


def anotar_estatus_efectivo(qs):
    """Agrega `_estatus_chip` (clave del chip al que pertenece cada FUS) al
    queryset — mismo criterio que `estatus_visual`, resuelto en SQL."""
    turnados = Turnado.objects.filter(idFus=OuterRef('pk'), activo=1).order_by()
    cuantos = Subquery(
        turnados.values('idFus').annotate(n=Count('id')).values('n'),
        output_field=IntegerField(),
    )
    unico = Subquery(turnados.values('estatusTitular_id')[:1], output_field=CharField())
    visual = Case(
        When(
            Q(_n_turnados=1) & ~Q(_estatus_turnado_unico='Recibido'),
            then=F('_estatus_turnado_unico'),
        ),
        default=F('estatusParticular'),
        output_field=CharField(),
    )
    chip = Case(
        *[When(_estatus_visual=origen, then=Value(destino)) for origen, destino in CHIP_DE_ESTATUS.items()],
        default=F('_estatus_visual'),
        output_field=CharField(),
    )
    return (
        qs.annotate(_n_turnados=cuantos, _estatus_turnado_unico=unico)
        .annotate(_estatus_visual=visual)
        .annotate(_estatus_chip=chip)
    )
