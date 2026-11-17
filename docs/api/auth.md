# API de autenticación (`/api/v1/auth`) y salud

Todos los errores son JSON `{"detail": "<español claro>", "code": "SNAKE_CASE"}` (los 422 agregan `errores: [{campo, mensaje}]`).
Access token: `Authorization: Bearer <jwt>` (8 h). Refresh token: cookie **HttpOnly** `sti_refresh` (path `/api/v1/auth`, `SameSite=Lax` por defecto,
14 días, **rotación en cada uso**). Con el proxy Cloudflare Pages las cookies quedan same-origin.

## Objeto `Me`

```json
{ "id": 7, "email": "x@unicordoba.edu.co", "nombre_completo": "…", "rol": "ESTUDIANTE",
  "estado": "ACTIVO", "consentimiento_firmado": true, "programa_id": 1,
  "preferencias_ui": { "modo_calma": false, "tamano_texto": 100, "espaciado": "NORMAL",
                       "sin_movimiento": false, "alto_contraste": false, "fuente": "PREDETERMINADA" } }
```

* `rol`: `ADMIN | BIENESTAR | COORDINADOR | DOCENTE | ESTUDIANTE | FAMILIAR`.
* `estado`: `PENDIENTE_ACTIVACION | PENDIENTE_CONSENTIMIENTO | ACTIVO | INACTIVO | SUSPENDIDO`.
* `consentimiento_firmado`: para ESTUDIANTE = F0 firmado y vigente; para los demás roles siempre `true`.
  Un estudiante con `false` debe ser redirigido a F0; el resto de la API le responde `403 CONSENTIMIENTO_REQUERIDO`.
* `preferencias_ui.tamano_texto`: `100 | 115 | 130`; `espaciado`: `NORMAL | AMPLIO | MUY_AMPLIO`; `fuente`: `PREDETERMINADA | DISLEXIA | SISTEMA`.

## Endpoints

| Método y ruta | Auth | Cuerpo | Respuesta | Errores (`code`) |
|---|---|---|---|---|
| `POST /auth/login` | — | `{email, password}` | `200 {access_token, token_type:"bearer", expires_in, user: Me}` + cookie refresh | `401 CREDENCIALES_INVALIDAS`, `423 CUENTA_BLOQUEADA` (5 intentos → 15 min; incluye `bloqueada_hasta`), `403 CUENTA_NO_ACTIVADA`, `403 CUENTA_INACTIVA`, `429 DEMASIADOS_INTENTOS` |
| `POST /auth/refresh` | cookie | — | igual que login (nuevo access + `user`) y cookie rotada | `401 REFRESH_AUSENTE / REFRESH_INVALIDO / REFRESH_EXPIRADO / REFRESH_REUTILIZADO` (reuso ⇒ se revoca toda la sesión) |
| `POST /auth/logout` | cookie | — | `200 {detail}` y borra la cookie | — |
| `POST /auth/activate` | — | `{token, password}` | `200 {detail, email, estado}` | `400 TOKEN_ACTIVACION_INVALIDO / TOKEN_ACTIVACION_VENCIDO` (72 h), `422 CONTRASENA_DEBIL`, `409 CUENTA_YA_ACTIVADA` |
| `POST /auth/forgot-password` | — | `{email}` | `200 {detail}` (siempre igual) | `429` |
| `POST /auth/reset-password` | — | `{token, password}` | `200 {detail}` (cierra todas las sesiones) | `400 TOKEN_RECUPERACION_INVALIDO / TOKEN_RECUPERACION_VENCIDO`, `422 CONTRASENA_DEBIL` |
| `POST /auth/change-password` | Bearer | `{password_actual, password_nueva}` | `200 {detail}` | `400 CONTRASENA_ACTUAL_INCORRECTA`, `422 CONTRASENA_DEBIL` |
| `GET /auth/me` | Bearer | — | `Me` | `401 NO_AUTENTICADO / TOKEN_INVALIDO / TOKEN_EXPIRADO` |
| `PATCH /auth/me/preferencias` | Bearer | parcial: `{modo_calma?, tamano_texto?: 100\|115\|130, espaciado?, sin_movimiento?, alto_contraste?, fuente?}` (acepta mayúsculas/minúsculas) | `200 Me` (con `preferencias_ui` al día) | `422 DATOS_INVALIDOS` |
| `GET /auth/sso/login` | — | — | `302` al proveedor OIDC | `501 SSO_NO_CONFIGURADO` |
| `GET /auth/sso/callback` | — | `?code&state` | `302` a `{FRONTEND_URL}/login?sso=ok|error|sin_cuenta|inactiva` con la cookie de refresh puesta (el SPA llama `POST /auth/refresh` para obtener el access token) | `501 SSO_NO_CONFIGURADO`, `400 SSO_STATE_INVALIDO` |
| `GET /health` y `GET /api/v1/health` | — | — | `{status:"ok"\|"degradado", version, entorno, base_de_datos, tareas, correo, almacenamiento}` (503 si no hay BD) | — |

Política de contraseña: mínimo 10 caracteres, con al menos una letra y un número.
Enlaces de correo (configurables): `{FRONTEND_URL}/activar?token=…` y `{FRONTEND_URL}/restablecer?token=…`.

## Flujo del frontend

1. `POST /auth/login` → guardar `access_token` en memoria; refrescar con `POST /auth/refresh` ante `401 TOKEN_EXPIRADO` o al recargar la página.
2. Si `user.rol == "ESTUDIANTE"` y `!user.consentimiento_firmado` → ruta F0.
3. Tras `403 CONSENTIMIENTO_REQUERIDO` en cualquier llamada → redirigir a F0.
