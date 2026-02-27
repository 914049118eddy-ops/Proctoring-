import os
import base64
import threading
import uvicorn
import pandas as pd
import json
import hashlib
import logging
import csv
import io 
from openpyxl.styles import PatternFill, Font, Alignment
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional

from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

# ==========================================
# 0. CONFIGURACIÓN E INFRAESTRUCTURA BASE
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | PROCTORING-CORE | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("CoreAcademico")

# --- Excepciones Personalizadas ---
class AccesoDenegadoError(Exception): pass
class EntornoNoEncontradoError(Exception): pass
class HeartbeatDTO(BaseModel):
    uid: str
    sala: str

# ==========================================
# 1. CAPA DE SEGURIDAD (Singleton & Hashing)
# ==========================================
class GestorSeguridadInstitucional:
    """Maneja la criptografía de credenciales garantizando una única instancia (Singleton)."""
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

    def autenticar_docente(self, docente: str, password: str) -> str:
        try:
            with open(self.archivo_docentes, "r", encoding="utf-8") as f:
                docentes = json.load(f)
            
            datos_docente = docentes.get(docente)
            if datos_docente and datos_docente["password_hash"] == self.encriptar_clave(password):
                return datos_docente["sala_asignada"]
        except Exception as e:
            logger.error(f"Falla de E/S en autenticación: {e}")
        
        raise AccesoDenegadoError("Credenciales inválidas o usuario inexistente.")

# ==========================================
# 2. CAPA DE PERSISTENCIA (Manejo de Archivos)
# ==========================================
class ContextoDatos:
    """Abstracción thread-safe para operaciones CRUD sobre archivos CSV."""
    def __init__(self):
        self.lock = threading.Lock()
        self.estructura = {
            "db": {"archivo": "database.csv", "cols": ["Fecha", "ID", "Nombre", "Sala", "Falta", "Ruta"]},
            # Añadimos 'Ultimo_Pulso' y 'Faltas' a la asistencia
            "asistencia": {"archivo": "asistencia.csv", "cols": ["ID", "Nombre", "Sala", "Estado", "Camara", "Inicio", "Ultimo_Pulso", "Faltas"]},
            "respuestas": {"archivo": "respuestas.csv", "cols": ["ID", "Respuestas", "Fecha"]},
            "salas": {"archivo": "salas.csv", "cols": ["Sala", "Creado", "Docente"]},
            "logs": {"archivo": "system_logs.csv", "cols": ["Timestamp", "Evento", "Usuario"]}
        }
        self._auditar_entorno()

    def _auditar_entorno(self) -> None:
        for d in ["evidencias", "static", "static/js"]: 
            os.makedirs(d, exist_ok=True)
            
        for key, meta in self.estructura.items():
            ruta = meta["archivo"]
            if not os.path.exists(ruta) or os.stat(ruta).st_size == 0:
                pd.DataFrame(columns=meta["cols"]).to_csv(ruta, index=False)

    def insertar(self, entidad: str, datos: Dict[str, Any]) -> None:
        """Inserción directa por flujo de archivos para mayor eficiencia."""
        with self.lock:
            ruta = self.estructura[entidad]["archivo"]
            columnas = self.estructura[entidad]["cols"]
            file_exists = os.path.isfile(ruta)
            
            with open(ruta, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columnas)
                # No necesitamos escribir cabecera aquí si ya se hizo en _auditar_entorno
                writer.writerow(datos)

    # El método actualizar_campo sigue usando pandas por la complejidad de edición de filas
    def actualizar_campo(self, entidad: str, clave_primaria: str, campo: str, valor: Any) -> None:
        with self.lock:
            ruta = self.estructura[entidad]["archivo"]
            try:
                df = pd.read_csv(ruta)
                # Normalización de tipos para comparación segura
                df['ID'] = df['ID'].astype(str)
                df.loc[df['ID'] == str(clave_primaria), campo] = valor
                df.to_csv(ruta, index=False)
            except Exception as e:
                logger.error(f"Fallo en actualización atómica: {e}")

    def recuperar_todos(self, entidad: str) -> List[Dict[str, Any]]:
        ruta = self.estructura[entidad]["archivo"]
        try:
            if not os.path.exists(ruta): return []
            df = pd.read_csv(ruta)
            return df.to_dict(orient="records") if not df.empty else []
        except Exception as e:
            logger.error(f"Error de lectura en {ruta}: {e}")
            return []

    def purgar_tabla(self, entidad: str) -> None:
        with self.lock:
            ruta = self.estructura[entidad]["archivo"]
            pd.DataFrame(columns=self.estructura[entidad]["cols"]).to_csv(ruta, index=False)

# ==========================================
# 3. CAPA LÓGICA DE NEGOCIO (Core Académico)
# ==========================================
class MotorLMS:
    """Contiene las reglas de negocio universitarias."""
    def __init__(self, db: ContextoDatos, auth: GestorSeguridadInstitucional):
        self.db = db
        self.auth = auth
        self.config_path = "examen_config.json"

    def inicializar_sala(self, sala: str, docente: str, password: str) -> str:
        sala_norm = sala.strip().upper()
        if not self._sala_existe(sala_norm):
            self.db.insertar("salas", {"Sala": sala_norm, "Creado": datetime.now().strftime("%Y-%m-%d %H:%M"), "Docente": docente})
        
        self.auth.registrar_docente(docente, password, sala_norm)
        self.db.insertar("logs", {"Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Evento": f"Creación/Asignación de Sala {sala_norm}", "Usuario": docente})
        return sala_norm

    def _sala_existe(self, sala: str) -> bool:
        return any(s['Sala'].strip().upper() == sala for s in self.db.recuperar_todos("salas"))

    def procesar_acceso_alumno(self, uid: str, nombre: str, sala: str) -> bool:
        sala_norm = sala.strip().upper()
        if not self._sala_existe(sala_norm):
            raise EntornoNoEncontradoError(f"El entorno {sala_norm} no está activo.")
        
        # Inicializamos con 0 faltas y el pulso actual
        datos_acceso = {
            "ID": uid, "Nombre": nombre, "Sala": sala_norm, 
            "Estado": "EN EXAMEN", "Camara": "OK", 
            "Inicio": datetime.now().strftime("%H:%M:%S"),
            "Ultimo_Pulso": datetime.now().strftime("%H:%M:%S"),
            "Faltas": 0
        }
        self.db.insertar("asistencia", datos_acceso)
        self.db.insertar("logs", {"Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Evento": "Conexión de alumno", "Usuario": uid})
        return True

    def recepcionar_examen(self, uid: str, payload_respuestas: str) -> None:
        datos = {"ID": uid, "Respuestas": payload_respuestas, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self.db.insertar("respuestas", datos)
        self.db.actualizar_campo("asistencia", uid, "Estado", "FINALIZADO")

    def parametrizar_examen(self, sala: str, tipo: str, contenido: str) -> None:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_global = json.load(f)
        except:
            config_global = {}

        config_global[sala] = {"tipo": tipo, "url": contenido if tipo == "tradicional" else "", "preguntas": []}
        if tipo == "interactivo":
            try: config_global[sala]["preguntas"] = json.loads(contenido)
            except ValueError: logger.error("JSON interactivo inválido ignorado.")

        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config_global, f, indent=4)

    def obtener_parametros(self, sala: str) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config_global = json.load(f)
            return config_global.get(sala, {"tipo": "tradicional", "url": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg", "preguntas": []})
        except:
            return {"tipo": "tradicional", "url": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg", "preguntas": []}

# ==========================================
# 4. CAPA DE ANÁLISIS E INTELIGENCIA ARTIFICIAL
# ==========================================
class EvidenciaIADTO(BaseModel):
    uid: str
    nombre: str
    sala: str
    tipo_falta: str
    imagen_b64: str
    camara_ok: bool

class MotorAuditoriaIA:
    """Indexa y procesa las penalizaciones enviadas por los tensores WebAssembly."""
    def __init__(self, db: ContextoDatos):
        self.db = db

    def evaluar_infraccion(self, dto: EvidenciaIADTO) -> None:
        timestamp = datetime.now().strftime("%H%M%S")
        ruta_img = f"evidencias/{dto.uid}_{timestamp}.jpg"
        
        try:
            header, encoded = dto.imagen_b64.split(",", 1) if "," in dto.imagen_b64 else ("", dto.imagen_b64)
            with open(ruta_img, "wb") as f:
                f.write(base64.b64decode(encoded))
        except Exception as e:
            logger.error(f"Decodificación visual fallida: {e}")

        if not dto.camara_ok:
            self.db.actualizar_campo("asistencia", dto.uid, "Camara", "BLOQUEADA")

        self.db.insertar("db", {
            "Fecha": datetime.now().strftime("%H:%M:%S"),
            "ID": dto.uid, "Nombre": dto.nombre, "Sala": dto.sala, 
            "Falta": dto.tipo_falta, "Ruta": ruta_img
        })
    def procesar_sancion(self, dto: EvidenciaIADTO) -> str:
        """Incrementa el contador de faltas y decide si bloquea al estudiante."""
        # 1. Recuperar registro del alumno
        asistencia = self.db.recuperar_todos("asistencia")
        alumno = next((a for a in asistencia if str(a.get("ID")) == dto.uid), None)
        
        estado_actual = "INDEXADO"
        
        if alumno:
            faltas_actuales = int(alumno.get("Faltas", 0)) + 1
            self.db.actualizar_campo("asistencia", dto.uid, "Faltas", faltas_actuales)
            
            # REGLAS DE ORO DE PENALIZACIÓN:
            # - 3 faltas leves (Mirada desviada, Cambio de Pestaña) = Bloqueo
            # - 1 falta grave (Celular Detectado) = Bloqueo Inmediato
            es_falta_grave = "Celular" in dto.tipo_falta 
            
            if faltas_actuales >= 3 or es_falta_grave:
                self.db.actualizar_campo("asistencia", dto.uid, "Estado", "BLOQUEADO")
                estado_actual = "BLOQUEADO"
        
        return estado_actual

    def exportar_excel_estetico(self, sala: str, tipo_reporte: str) -> io.BytesIO:
        """Genera un archivo Excel en memoria estilizado con colores UNI."""
        output = io.BytesIO()
        
        if tipo_reporte == "infracciones":
            df = pd.DataFrame([i for i in self.db.recuperar_todos("db") if i.get("Sala") == sala])
            nombre_hoja = "Auditoría Forense"
        else:
            # Consolidamos Asistencia + Respuestas
            asist_df = pd.DataFrame([a for a in self.db.recuperar_todos("asistencia") if a.get("Sala") == sala])
            resp_df = pd.DataFrame([r for r in self.db.recuperar_todos("respuestas")])
            if not asist_df.empty and not resp_df.empty:
                df = pd.merge(asist_df, resp_df, on="ID", how="left")
            else:
                df = asist_df
            nombre_hoja = "Registro Académico"

        if df.empty:
            df = pd.DataFrame({"Mensaje": ["No hay datos registrados para esta sala."]})

        # Escribimos usando openpyxl
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=nombre_hoja)
            worksheet = writer.sheets[nombre_hoja]
            
            # Estilo Institucional FIEE UNI (Granate #800000)
            header_fill = PatternFill(start_color="800000", end_color="800000", fill_type="solid")
            header_font = Font(color="FFFFFF", bold=True)
            
            for col_num, cell in enumerate(worksheet[1], 1):
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
            # Auto-ajustar el ancho de las columnas
            for column_cells in worksheet.columns:
                length = max(len(str(cell.value) or "") for cell in column_cells)
                worksheet.column_dimensions[column_cells[0].column_letter].width = length + 5

        output.seek(0)
        return output
    
    def consolidar_dashboard_docente(self, sala: str) -> Tuple[Dict, List, List, List]:
        asistencia = [a for a in self.db.recuperar_todos("asistencia") if a.get("Sala") == sala]
        incidencias = [i for i in self.db.recuperar_todos("db") if i.get("Sala") == sala]
        ids_presentes = {a.get("ID") for a in asistencia if a.get("ID")}
        respuestas_crudas = [r for r in self.db.recuperar_todos("respuestas") if r.get("ID") in ids_presentes]
        
        respuestas_formateadas = []
        for r in respuestas_crudas:
            try: r['Detalle'] = json.loads(r['Respuestas'])
            except: r['Detalle'] = {"Error": "Datos corruptos"}
            respuestas_formateadas.append(r)
        
        metricas = {
            "total_alumnos": len(asistencia),
            "activos": sum(1 for a in asistencia if a.get("Estado") == "EN EXAMEN"),
            "camaras_tapadas": sum(1 for a in asistencia if a.get("Camara") == "BLOQUEADA"),
            "total_alertas": len(incidencias)
        }
        return metricas, incidencias[::-1], asistencia[::-1], respuestas_formateadas[::-1]

    def limpieza_profunda(self) -> None:
        self.db.purgar_tabla("db")
        target_dir = "evidencias"
        for archivo in os.listdir(target_dir):
            if archivo.endswith(".jpg"):
                try: os.remove(os.path.join(target_dir, archivo))
                except Exception: pass

# ==========================================
# 5. INICIALIZACIÓN Y DEPENDENCIAS
# ==========================================
db_context = ContextoDatos()
auth_service = GestorSeguridadInstitucional()
lms_engine = MotorLMS(db_context, auth_service)
proctor_engine = MotorAuditoriaIA(db_context)

# Funciones de Inyección de Dependencias
def get_lms() -> MotorLMS: return lms_engine
def get_proctor() -> MotorAuditoriaIA: return proctor_engine

app = FastAPI(title="Proctoring Framework FIEE", version="3.0")
app.add_middleware(SessionMiddleware, secret_key="hash_absoluto_fiee_2026")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

# ==========================================
# 6. MANEJO GLOBAL DE EXCEPCIONES
# ==========================================
@app.exception_handler(AccesoDenegadoError)
async def auth_exception_handler(request: Request, exc: AccesoDenegadoError):
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "error", "titulo": "Acceso Denegado", "mensaje": str(exc)
    })

@app.exception_handler(EntornoNoEncontradoError)
async def environment_exception_handler(request: Request, exc: EntornoNoEncontradoError):
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "error", "titulo": "Sala Inexistente", "mensaje": str(exc)
    })

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Esto atrapa el famoso "Not Found" y el "Method Not Allowed"
    if exc.status_code in [404, 405]:
        return templates.TemplateResponse("index.html", {
            "request": request, "vista": "error", 
            "titulo": f"Error {exc.status_code}", 
            "mensaje": "La ruta solicitada no es válida o intentaste recargar un formulario de manera insegura."
        })
    return HTMLResponse(f"<h1>Error Crítico {exc.status_code}</h1>", status_code=exc.status_code)

# ==========================================
# 7. CONTROLADORES HTTP (RUTAS RESTful)
# ==========================================
@app.post("/api/heartbeat")
async def endpoint_heartbeat(data: HeartbeatDTO):
    """Actualiza el timestamp de última conexión del estudiante."""
    db_context.actualizar_campo("asistencia", data.uid, "Ultimo_Pulso", datetime.now().strftime("%H:%M:%S"))
    return {"status": "ok"}

@app.post("/api/alerta_ia")
async def endpoint_alerta_ia(alerta: EvidenciaIADTO, bt: BackgroundTasks, proctor: MotorAuditoriaIA = Depends(get_proctor)):
    # 1. Evaluamos la sanción síncronamente para responder de inmediato
    estado_bloqueo = proctor.procesar_sancion(alerta)
    
    # 2. Guardamos la imagen pesada en segundo plano para no bloquear el hilo de la API
    bt.add_task(proctor.evaluar_infraccion, alerta)
    
    return {"estado": estado_bloqueo}

@app.get("/descargar_excel/{tipo}")
async def endpoint_descarga_excel(request: Request, tipo: str, proctor: MotorAuditoriaIA = Depends(get_proctor)):
    if "docente" not in request.session:
        raise HTTPException(status_code=403, detail="No autorizado")
    
    sala = request.session['sala']
    
    if tipo not in ["infracciones", "asistencia"]:
        raise HTTPException(status_code=400, detail="Tipo de reporte inválido")
        
    archivo_bytes = proctor.exportar_excel_estetico(sala, tipo)
    
    return StreamingResponse(
        archivo_bytes, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
        headers={"Content-Disposition": f"attachment; filename=Reporte_{tipo.capitalize()}_{sala}.xlsx"}
    )

@app.get("/", response_class=HTMLResponse)
async def home_portal(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "vista": "registro"})

@app.post("/crear_sala")
async def endpoint_crear_sala(request: Request, docente: str = Form(...), nombre_sala: str = Form(...), password: str = Form(...), lms: MotorLMS = Depends(get_lms)):
    sala_id = lms.inicializar_sala(nombre_sala, docente, password)
    request.session["docente"] = docente
    request.session["sala"] = sala_id
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/login_docente")
async def endpoint_login_docente(request: Request, docente: str = Form(...), password: str = Form(...)):
    sala_asignada = auth_service.autenticar_docente(docente, password)
    request.session["docente"] = docente
    request.session["sala"] = sala_asignada
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/ingresar_alumno")
async def endpoint_ingreso_alumno(nombre: str = Form(...), uid: str = Form(...), sala: str = Form(...), lms: MotorLMS = Depends(get_lms)):
    lms.procesar_acceso_alumno(uid, nombre, sala)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala.upper()}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def endpoint_vista_examen(request: Request, uid: str, nombre: str, sala: str, lms: MotorLMS = Depends(get_lms)):
    config = lms.obtener_parametros(sala.upper())
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "examen", "uid": uid, "nombre": nombre, "sala": sala, "config": config
    })

@app.post("/finalizar_evaluacion")
async def endpoint_finalizar(request: Request, uid: str = Form(...), respuestas: str = Form(...), lms: MotorLMS = Depends(get_lms)):
    lms.recepcionar_examen(uid, respuestas)
    return templates.TemplateResponse("index.html", {"request": request, "vista": "confirmacion"})

@app.get("/dashboard", response_class=HTMLResponse)
async def endpoint_dashboard(request: Request, proctor: MotorAuditoriaIA = Depends(get_proctor)):
    if "docente" not in request.session:
        return RedirectResponse(url="/")
        
    docente = request.session["docente"]
    sala = request.session["sala"]
    stats, incidencias, asistencia, respuestas = proctor.consolidar_dashboard_docente(sala)
    
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "dashboard", "stats": stats, 
        "incidencias": incidencias, "asistencia": asistencia, 
        "respuestas": respuestas, "docente": docente, "sala": sala
    })

@app.post("/configurar_lms")
async def endpoint_configurar_examen(request: Request, tipo: str = Form(...), contenido: str = Form(...), lms: MotorLMS = Depends(get_lms)):
    if "sala" in request.session:
        lms.parametrizar_examen(request.session["sala"], tipo, contenido)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/limpiar_auditoria")
async def endpoint_limpiar(request: Request, proctor: MotorAuditoriaIA = Depends(get_proctor)):
    if "docente" in request.session:
        proctor.limpieza_profunda()
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/logout")
async def endpoint_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/descargar_dataset")
async def endpoint_descarga(request: Request):
    if "docente" in request.session and os.path.exists("database.csv"): 
        return FileResponse("database.csv", filename=f"Auditoria_{request.session['sala']}.csv")
    raise HTTPException(status_code=404, detail="Archivo no encontrado")

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=puerto)




