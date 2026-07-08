from django.db import models


class CorreoAutorizado(models.Model):
    """Lista blanca de correos @anam.gob.mx con acceso al sistema (RN-06, CU-01)."""

    class Meta:
        db_table = 'scs_cat_correos_autorizados'

    ROL_CHOICES = [
        ('ROL1', 'Particular del Titular'),
        ('ROL2', 'Titular / Enlace Estratégico'),
    ]

    email = models.EmailField(unique=True)
    nombre = models.CharField(max_length=255)
    rol = models.CharField(max_length=10, choices=ROL_CHOICES)
    unidadAdministrativa = models.ForeignKey(
        'catalogos.UnidadAdministrativa', null=True, blank=True,
        on_delete=models.SET_NULL, db_constraint=False,
        related_name='correos_autorizados',
    )
    fechaRegistro = models.DateTimeField(auto_now_add=True, null=True)
    fechaModificacion = models.DateTimeField(auto_now=True, null=True)
    idUsuarioRegistra = models.IntegerField(null=True, blank=True)
    idUsuarioModifica = models.IntegerField(null=True, blank=True)
    activo = models.IntegerField(default=1)

    def __str__(self):
        return f"{self.email} ({self.rol})"


class CodigoOTP(models.Model):
    """OTP de verificación para primer acceso y recuperación de contraseña (CU-01, CU-02)."""

    class Meta:
        db_table = 'scs_tbl_codigos_otp'

    email = models.EmailField()
    codigo = models.CharField(max_length=10)
    fechaGeneracion = models.DateTimeField(auto_now_add=True)
    fechaExpiracion = models.DateTimeField()
    usado = models.IntegerField(default=0)
    ipSolicitante = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"OTP {self.email} – {'usado' if self.usado else 'vigente'}"
