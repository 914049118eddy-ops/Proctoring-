import os
import base64
import threading
import uvicorn
import pandas as pd
import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

# ==========================================
# CONFIGURACIÓN DE LOGGING INSTITUCIONAL
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | FIEE-PROCTORING | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ProctoringFIEE")

# ==========================================
# DATA TRANSFER OBJECTS (DTOs) CON PYDANTIC
# ==========================================
class EvidenciaIADTO(BaseModel):
    """Modelo robusto para la validación de datos de IA."""
    uid: str = Field(..., min_length=3, description="Código del estudiante")
    nombre: str = Field(..., min_length=3, description="Nombre completo")
    sala: str = Field(..., description="Sala de evaluación")
    tipo_falta: str = Field(..., description="Clasificación de la infracción")
    imagen_b64: str = Field(..., description="Fotografía codificada en Base64")
    camara_ok: bool = Field(..., description="Estado de obstrucción de la cámara")

# ==========================================
# 1. CAPA DE SEGURIDAD (Criptografía Hash)
# ==========================================
class GestorSeguridadInstitucional:
    """Implementa Singleton y Hashing para credenciales docentes."""
    _instancia = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instancia is None:
                cls._instancia = super(GestorSeguridadInstitucional, cls).__new__(cls)
        return cls._instancia

    def __init__(self, archivo_docentes: str = "docentes.json"):
        if not hasattr(self, 'inicializado'):
            self.archivo_docentes = Path(archivo_docentes)
            self.lock = threading.Lock()
            self._inicializar_registro()
            self.inicializado = True

    def _inicializar_registro(self) -> None:
        if not self.archivo_docentes.exists():
            with open(self.archivo_docentes, "w", encoding="utf-8") as f:
                json.dump({}, f)
            logger.info("Base de datos de credenciales inicializada.")

    def encriptar_clave(self, password: str) -> str:
        return hashlib.sha256(password.encode('utf-8')).hexdigest()

    def registrar_docente(self, docente: str, password: str, sala: str) -> None:
        with self.lock:
            with open(self.archivo_docentes, "r", encoding="utf-8") as f:
                docentes = json.load(f)
            
            docentes[docente] = {
                "password_hash": self.encriptar_clave(password),
                "sala_asignada": sala.upper(),
                "fecha_registro": datetime.now().isoformat()
            }
            
            with open(self.archivo_docentes, "w", encoding="utf-8") as f:
                json.dump(docentes, f, indent=4)
            logger.info(f"Docente '{docente}' registrado con acceso a la sala {sala}.")

    def autenticar_docente(self, docente: str, password: str) -> Optional[str]:
        try:
            with open(self.archivo_docentes, "r", encoding="utf-8") as f:
                docentes = json.load(f)
            
            datos_docente = docentes.get(docente)
            if datos_docente and datos_docente["password_hash"] == self.encriptar_clave(password):
                logger.info(f"Autenticación exitosa para docente '{docente}'.")
                return datos_docente["sala_asignada"]
        except Exception as e:
            logger.error(f"Error en autenticación: {e}")
        
        logger.warning(f"Intento de acceso fallido para usuario '{docente}'.")
        return None

# ==========================================
# 2. CAPA DE PERSISTENCIA (Manejo de Archivos)
# ==========================================
class ContextoDatos:
    """Provee acceso thread-safe a las bases de datos CSV."""
    def __init__(self):
        self.lock = threading.Lock()
        self.estructura = {
            "db": {"archivo": "database.csv", "cols": ["Fecha", "ID", "Nombre", "Sala", "Falta", "Ruta"]},
            "asistencia": {"archivo": "asistencia.csv", "cols": ["ID", "Nombre", "Sala", "Estado", "Camara", "Inicio"]},
            "respuestas": {"archivo": "respuestas.csv", "cols": ["ID", "Respuestas", "Fecha"]},
            "salas": {"archivo": "salas.csv", "cols": ["Sala", "Creado", "Docente"]}
        }
        self._auditar_entorno()

    def _auditar_entorno(self) -> None:
        for d in ["evidencias", "static", "static/js"]: 
            os.makedirs(d, exist_ok=True)
            
        for key, meta in self.estructura.items():
            ruta = meta["archivo"]
            if not os.path.exists(ruta) or os.stat(ruta).st_size == 0:
                pd.DataFrame(columns=meta["cols"]).to_csv(ruta, index=False)
                logger.info(f"Archivo {ruta} creado con estructura base.")

    def insertar(self, entidad: str, datos: Dict[str, Any]) -> None:
        with self.lock:
            ruta = self.estructura[entidad]["archivo"]
            pd.DataFrame([datos]).to_csv(ruta, mode='a', header=False, index=False)

    def actualizar_campo(self, entidad: str, clave_primaria: str, campo: str, valor: Any) -> None:
        with self.lock:
            ruta = self.estructura[entidad]["archivo"]
            df = pd.read_csv(ruta)
            df.loc[df['ID'] == clave_primaria, campo] = valor
            df.to_csv(ruta, index=False)

    def recuperar_todos(self, entidad: str) -> List[Dict[str, Any]]:
        ruta = self.estructura[entidad]["archivo"]
        if not os.path.exists(ruta): return []
        return pd.read_csv(ruta).to_dict(orient="records")

    def purgar_tabla(self, entidad: str) -> None:
        with self.lock:
            ruta = self.estructura[entidad]["archivo"]
            pd.DataFrame(columns=self.estructura[entidad]["cols"]).to_csv(ruta, index=False)
            logger.info(f"Tabla {entidad} purgada exitosamente.")

# ==========================================
# 3. CAPA LÓGICA DE NEGOCIO (Core Académico)
# ==========================================
class MotorLMS:
    """Orquesta las operaciones del aula virtual."""
    def __init__(self, db: ContextoDatos, auth: GestorSeguridadInstitucional):
        self.db = db
        self.auth = auth
        self.config_path = "examen_config.json"

    def inicializar_sala(self, sala: str, docente: str, password: str) -> str:
        sala_norm = sala.strip().upper()
        if self._sala_existe(sala_norm):
            logger.warning(f"La sala {sala_norm} ya existe. Reasignando credenciales.")
        else:
            self.db.insertar("salas", {"Sala": sala_norm, "Creado": datetime.now().strftime("%Y-%m-%d %H:%M"), "Docente": docente})
        
        self.auth.registrar_docente(docente, password, sala_norm)
        return sala_formateada

    def _sala_existe(self, sala: str) -> bool:
        return any(s['Sala'].strip().upper() == sala for s in self.db.recuperar_todos("salas"))

    def procesar_acceso_alumno(self, uid: str, nombre: str, sala: str) -> bool:
        sala_norm = sala.strip().upper()
        if not self._sala_existe(sala_norm):
            return False
        
        datos_acceso = {"ID": uid, "Nombre": nombre, "Sala": sala_norm, "Estado": "EN EXAMEN", "Camara": "OK", "Inicio": datetime.now().strftime("%H:%M:%S")}
        self.db.insertar("asistencia", datos_acceso)
        logger.info(f"Alumno {nombre} ({uid}) ingresó a la sala {sala_norm}.")
        return True

    def recepcionar_examen(self, uid: str, payload_respuestas: str) -> None:
        datos = {"ID": uid, "Respuestas": payload_respuestas, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self.db.insertar("respuestas", datos)
        self.db.actualizar_campo("asistencia", uid, "Estado", "FINALIZADO")
        logger.info(f"Examen finalizado para alumno {uid}.")

    def parametrizar_examen(self, sala: str, tipo: str, contenido: str) -> None:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_global = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            config_global = {}

        config_global[sala] = {"tipo": tipo, "url": contenido if tipo == "tradicional" else "", "preguntas": []}
        
        if tipo == "interactivo":
            try:
                config_global[sala]["preguntas"] = json.loads(contenido)
            except ValueError:
                logger.error("Error al decodificar JSON interactivo. Guardado como vacío.")

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_global, f, indent=4)
        logger.info(f"Configuración de examen actualizada para la sala {sala}.")

    def obtener_parametros(self, sala: str) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_global = json.load(f)
            return config_global.get(sala, {"tipo": "tradicional", "url": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg", "preguntas": []})
        except:
            return {"tipo": "tradicional", "url": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg", "preguntas": []}

# ==========================================
# 4. CAPA DE ANÁLISIS (Proctoring e IA)
# ==========================================
class MotorAuditoriaIA:
    """Evalúa e indexa las evidencias detectadas por los modelos ONNX."""
    def __init__(self, db: ContextoDatos):
        self.db = db

    def evaluar_infraccion(self, dto: EvidenciaIADTO) -> None:
        timestamp = datetime.now().strftime("%H%M%S")
        ruta_img = f"evidencias/{dto.uid}_{timestamp}.jpg"
        
        # Procesamiento I/O seguro
        try:
            header, encoded = dto.imagen_b64.split(",", 1) if "," in dto.imagen_b64 else ("", dto.imagen_b64)
            with open(ruta_img, "wb") as f:
                f.write(base64.b64decode(encoded))
        except Exception as e:
            logger.error(f"Fallo al decodificar evidencia visual de {dto.uid}: {e}")

        # Penalización cruzada si hay manipulación de hardware
        if not dto.camara_ok:
            self.db.actualizar_campo("asistencia", dto.uid, "Camara", "BLOQUEADA")

        # Inserción en bitácora
        registro_falta = {
            "Fecha": datetime.now().strftime("%H:%M:%S"),
            "ID": dto.uid, "Nombre": dto.nombre, "Sala": dto.sala, 
            "Falta": dto.tipo_falta, "Ruta": ruta_img
        }
        self.db.insertar("db", registro_falta)
        logger.warning(f"Infracción detectada: {dto.tipo_falta} | Alumno: {dto.uid} | Sala: {dto.sala}")

    def consolidar_dashboard_docente(self, sala: str) -> Tuple[Dict, List, List, List]:
        """Agrega y formatea datos aislando los correspondientes a la sala solicitada."""
        asistencia = [a for a in self.db.recuperar_todos("asistencia") if a["Sala"] == sala]
        incidencias = [i for i in self.db.recuperar_todos("db") if i["Sala"] == sala]
        
        ids_presentes = {a["ID"] for a in asistencia}
        respuestas_crudas = [r for r in self.db.recuperar_todos("respuestas") if r["ID"] in ids_presentes]
        
        # Parseo seguro de JSON de respuestas
        respuestas_formateadas = []
        for r in respuestas_crudas:
            try: r['Detalle'] = json.loads(r['Respuestas'])
            except: r['Detalle'] = {"Error": "Datos corruptos"}
            respuestas_formateadas.append(r)
        
        metricas = {
            "total_alumnos": len(asistencia),
            "activos": sum(1 for a in asistencia if a["Estado"] == "EN EXAMEN"),
            "camaras_tapadas": sum(1 for a in asistencia if a["Camara"] == "BLOQUEADA"),
            "total_alertas": len(incidencias)
        }
        
        return metricas, incidencias[::-1], asistencia[::-1], respuestas_formateadas[::-1]

    def limpieza_profunda(self) -> None:
        """Garbage Collector: Purgado de registros y recolección de archivos residuales."""
        self.db.purgar_tabla("db")
        target_dir = "evidencias"
        for archivo in os.listdir(target_dir):
            if archivo.endswith((".jpg", ".png")):
                try: 
                    os.remove(os.path.join(target_dir, archivo))
                except Exception as e: 
                    logger.error(f"Error purgando {archivo}: {e}")
        logger.info("Limpieza de auditoría ejecutada con éxito.")


# ==========================================
# 5. BOOTSTRAPPING Y CONSTRUCCIÓN DE LA APP
# ==========================================
db_context = ContextoDatos()
auth_service = GestorSeguridadInstitucional()
lms_engine = MotorLMS(db_context, auth_service)
proctor_engine = MotorAuditoriaIA(db_context)

app = FastAPI(title="Plataforma Proctoring FIEE", description="Sistema LMS con Supervisión de IA Distribuida", version="2.0")
app.add_middleware(SessionMiddleware, secret_key="llave_maestra_fiee_2026_super_segura")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

# ==========================================
# 6. MANEJO GLOBAL DE EXCEPCIONES (Fix del 404)
# ==========================================
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        logger.warning(f"Ruta no encontrada solicitada: {request.url.path}")
        return HTMLResponse("""
            <div style="text-align:center; padding:50px; font-family:sans-serif; background:#f4f7f6; height:100vh;">
                <h1 style="color:#800000; font-size:50px; margin-bottom:10px;">404</h1>
                <h2>Recurso No Encontrado</h2>
                <p>La ruta a la que intentas acceder no existe en la arquitectura del sistema.</p>
                <a href="/" style="background:#800000; color:white; padding:10px 20px; text-decoration:none; border-radius:5px; display:inline-block; margin-top:20px;">Volver al Portal Principal</a>
            </div>
        """, status_code=404)
    return HTMLResponse(f"<h1>Error {exc.status_code}</h1>", status_code=exc.status_code)

# ==========================================
# 7. CONTROLADORES HTTP (RUTAS RESTful)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def home_portal(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "vista": "registro"})

@app.post("/crear_sala")
async def endpoint_crear_sala(request: Request, docente: str = Form(...), nombre_sala: str = Form(...), password: str = Form(...)):
    sala_id = lms_engine.inicializar_sala(nombre_sala, docente, password)
    request.session["docente"] = docente
    request.session["sala"] = sala_id
    logger.info(f"Sesión iniciada como profesor para la sala {sala_id}.")
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/login_docente")
async def endpoint_login_docente(request: Request, docente: str = Form(...), password: str = Form(...)):
    sala_asignada = auth_service.autenticar_docente(docente, password)
    if sala_asignada:
        request.session["docente"] = docente
        request.session["sala"] = sala_asignada
        return RedirectResponse(url="/dashboard", status_code=303)
    return HTMLResponse("<div style='text-align:center; padding:50px; font-family:sans-serif;'><h1>❌ Credenciales Incorrectas</h1><a href='/'>Reintentar</a></div>", status_code=403)

@app.post("/ingresar_alumno")
async def endpoint_ingreso_alumno(nombre: str = Form(...), uid: str = Form(...), sala: str = Form(...)):
    if not lms_engine.procesar_acceso_alumno(uid, nombre, sala):
        return HTMLResponse("<div style='text-align:center; padding:50px; font-family:sans-serif;'><h1>❌ La sala especificada no existe.</h1><a href='/'>Reintentar</a></div>", status_code=404)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala.upper()}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def endpoint_vista_examen(request: Request, uid: str, nombre: str, sala: str):
    config = lms_engine.obtener_parametros(sala.upper())
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "examen", "uid": uid, "nombre": nombre, "sala": sala, "config": config
    })

@app.post("/finalizar_evaluacion")
async def endpoint_finalizar(uid: str = Form(...), respuestas: str = Form(...)):
    lms_engine.recepcionar_examen(uid, respuestas)
    return templates.TemplateResponse("index.html", {"request": {}, "vista": "confirmacion"})

@app.get("/dashboard", response_class=HTMLResponse)
async def endpoint_dashboard(request: Request):
    if "docente" not in request.session:
        logger.warning("Intento de acceso a dashboard sin sesión activa.")
        return RedirectResponse(url="/")
        
    docente = request.session["docente"]
    sala = request.session["sala"]
    
    stats, incidencias, asistencia, respuestas = proctor_engine.consolidar_dashboard_docente(sala)
    
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "dashboard", "stats": stats, 
        "incidencias": incidencias, "asistencia": asistencia, 
        "respuestas": respuestas, "docente": docente, "sala": sala
    })

@app.post("/configurar_lms")
async def endpoint_configurar_examen(request: Request, tipo: str = Form(...), contenido: str = Form(...)):
    if "sala" in request.session:
        lms_engine.parametrizar_examen(request.session["sala"], tipo, contenido)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/limpiar_auditoria")
async def endpoint_limpiar(request: Request):
    if "docente" in request.session:
        proctor_engine.limpieza_profunda()
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/logout")
async def endpoint_logout(request: Request):
    docente = request.session.get("docente", "Desconocido")
    request.session.clear()
    logger.info(f"Sesión cerrada para el docente {docente}.")
    return RedirectResponse(url="/")

@app.post("/api/alerta_ia")
async def endpoint_alerta_ia(alerta: EvidenciaIADTO, bt: BackgroundTasks):
    bt.add_task(proctor_engine.evaluar_infraccion, alerta)
    return {"estado": "Acuse de recibo confirmado"}

@app.get("/descargar_dataset")
async def endpoint_descarga(request: Request):
    if "docente" in request.session and os.path.exists("database.csv"): 
        return FileResponse("database.csv", filename=f"Auditoria_{request.session['sala']}.csv")
    raise HTTPException(status_code=404)

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8000))
    logger.info(f"Iniciando Servidor FIEE Proctoring en el puerto {puerto}")
    uvicorn.run("app:app", host="0.0.0.0", port=puerto)
