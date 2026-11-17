"""Modelos SQLAlchemy del STI. Importar este paquete registra TODAS las tablas en `Base.metadata`."""

from app.models import (  # noqa: F401  (el import registra las tablas)
    academico,
    apoyos,
    caracterizacion,
    consentimiento,
    contexto,
    dua,
    evaluacion,
    f10,
    mapa,
    plan,
    seguimiento,
    slice_b,
    sistema,
    trayectoria,
    usuarios,
)
from app.models.academico import (
    AsignacionDocente,
    Asignatura,
    CalendarioAcademico,
    Matricula,
    ProgramaAcademico,
    RegistroInasistencia,
)
from app.models.apoyos import (
    Apoyo,
    ImplementacionApoyo,
    Recurso,
    RegistroImplementacion,
    ResponsableApoyo,
    TipoApoyo,
)
from app.models.base import Base, HardDeleteForbidden, finalize_check_constraint_names
from app.models.caracterizacion import (
    Caracterizacion,
    DatoAutonomia,
    DatoComunicacion,
    DatoPreferencia,
    DatoSensorial,
    EstrategiaAprendizaje,
    Fortaleza,
    Interes,
    PerfilFortalezas,
)
from app.models.consentimiento import (
    AutorizacionFamiliar,
    Consentimiento,
    CuestionarioAQ10,
    RespuestaAQ10,
    SolicitudIngreso,
)
from app.models.contexto import (
    ContextoAula,
    ContextoCampus,
    ContextoDocente,
    ContextoEvaluacion,
    ContextoEvento,
    ContextoLaboratorio,
    ContextoPasantia,
    ContextoPracticaClinica,
    ContextoPracticaSaludPublica,
    ContextoUniversitario,
    ContextoVirtualidad,
)
from app.models.dua import CasoCbr, EstrategiaDuaCatalogo, SugerenciaDua
from app.models.evaluacion import DecisionPlan, EvaluacionPlan, NotaContinuidad
from app.models.f10 import F10Semestre
from app.models.mapa import (
    BarreraActitudinal,
    BarreraComunicativa,
    BarreraEvaluativa,
    BarreraIdentificada,
    BarreraInstitucional,
    BarreraPedagogica,
    BarreraSensorial,
    BarreraSocial,
    BarreraTecnologica,
    Facilitador,
    FacilitadorInstitucional,
    FacilitadorPedagogico,
    FacilitadorPersonal,
    FacilitadorSocial,
    FacilitadorTecnologico,
)
from app.models.plan import (
    AjusteRazonable,
    EstadoPlan,
    EstrategiaDua,
    FirmaPlan,
    PlanMaarTea,
    PlanVersion,
    RespuestaAmbiente,
    RespuestaComunicacion,
    RespuestaEvaluacion,
    RespuestaInteraccion,
    RespuestaPedagogia,
    RespuestaTecnologia,
    TareaNegociacion,
)
from app.models.seguimiento import (
    EvidenciaEfectividad,
    RegistroSeguimiento,
    RegistroSeguimientoAjuste,
    ResultadoIndicador,
    Seguimiento,
)
from app.models.sistema import (
    AuditoriaInmutableError,
    EmailOutbox,
    Exportacion,
    LogAuditoria,
    Notificacion,
    ParametroSistema,
)
from app.models.trayectoria import (
    Acceso,
    Aprendizaje,
    Autonomia,
    BienestarTrayectoria,
    Graduacion,
    HitoTrayectoria,
    Participacion,
    Permanencia,
    Progresion,
    TransicionProfesional,
    TrayectoriaAcademica,
)
from app.models.usuarios import (
    CoordinadorPrograma,
    Docente,
    Estudiante,
    PersonalAdministrativo,
    PersonalBienestar,
    PreferenciaSensorialUI,
    RefreshToken,
    Usuario,
)

# CHECK de los Enum no nativos con nombre determinista `ck_<tabla>_<columna>` (necesario para Alembic/PostgreSQL)
finalize_check_constraint_names(Base.metadata)


def table_count() -> int:
    return len(Base.metadata.tables)
