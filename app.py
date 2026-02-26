import os, base64, threading, uvicorn, pandas as pd, json, hashlib
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from typing import List, Dict, Tuple, Any, Optional

# ==========================================
# 1. CAPA DE SEGURIDAD Y CRIPTOGRAFÍA
# ==========================================
class GestorSeguridadInstitucional:
    """Maneja el encriptado de credenciales y validación de accesos docentes."""
    def __init__(self, archivo_docentes: str = "docentes.json"):
        self.archivo_docentes = archivo_docentes
        self.lock = threading.Lock()
        self._inicializar_registro()

    def _inicializar_registro(self) -> None:
        if not os.path.exists(self.archivo_docentes):
            with open(self.archivo_docentes, "w", encoding="utf-8") as f:
                json.dump({}, f)

    def encriptar_clave(self, password: str) -> str:
        """Aplica la función hash SHA-256 para almacenamiento seguro."""
        return hashlib.sha256(password.encode()).hexdigest()

    def registrar_docente(self, docente: str, password: str, sala: str) -> None:
        with self.lock:
            with open(self.archivo_docentes, "r", encoding="utf-8") as f:
                docentes = json.load(f)
            
            docentes[docente] = {
                "password_hash": self.encriptar_clave(password),
                "sala_asignada": sala.upper()
            }
            
            with open(self.archivo_docentes, "w", encoding="utf-8") as f:
                json.dump(docentes, f)

    def autenticar_docente(self, docente: str, password: str) -> Optional[str]:
        """Valida credenciales y retorna la sala asignada si es exitoso."""
        with open(self.archivo_docentes, "r", encoding="utf-8") as f:
            docentes = json.load(f)
            
        if docente in docentes:
            if docentes[docente]["password_hash"] == self.encriptar_clave(password):
                return docentes[docente]["sala_asignada"]
        return None

    def actualizar_password(self, docente: str, nueva_password: str) -> bool:
        with self.lock:
            with open(self.archivo_docentes, "r", encoding="utf-8") as f:
                docentes = json.load(f)
                
            if docente in docentes:
                docentes[docente]["password_hash"] = self.encriptar_clave(nueva_password)
                with open(self.archivo_docentes, "w", encoding="utf-8") as f:
                    json.dump(docentes, f)
                return True
        return False

# ==========================================
# 2. CAPA DE DATOS Y PERSISTENCIA (POO)
# ==========================================
class RepositorioDatosFIEE:
    """Clase encargada de la gestión de archivos y seguridad de hilos."""
    def __init__(self):
        self.lock = threading.Lock()
        self.archivos = {
            "db": "database.csv",
            "asistencia": "asistencia.csv",
            "respuestas": "respuestas.csv",
            "salas": "salas.csv"
        }
        self.columnas = {
            "db": ["Fecha", "ID", "Nombre", "Sala", "Falta", "Ruta"],
            "asistencia": ["ID", "Nombre", "Sala", "Estado", "Camara", "Inicio"],
            "respuestas": ["ID", "Respuestas", "Fecha"],
            "salas": ["Sala", "Creado", "Docente"]
        }
        self._inicializar_entorno()

    def _inicializar_entorno(self) -> None:
        for directorio in ["evidencias", "static/js"]: 
            os.makedirs(directorio, exist_ok=True)
            
        for clave, ruta in self.archivos.items():
            if not os.path.exists(ruta) or os.stat(ruta).st_size == 0:
                pd.DataFrame(columns=self.columnas[clave]).to_csv(ruta, index=False)

    def guardar_registro(self, clave_archivo: str, registro: Dict[str, Any]) -> None:
        with self.lock:
            ruta = self.archivos[clave_archivo]
            pd.DataFrame([registro]).to_csv(ruta, mode='a', header=False, index=False)

    def actualizar_estado(self, clave_archivo: str, id_busqueda: str, columna: str, nuevo_valor: str) -> None:
        with self.lock:
            ruta = self.archivos[clave_archivo]
            df = pd.read_csv(ruta)
            df.loc[df['ID'] == id_busqueda, columna] = nuevo_valor
            df.to_csv(ruta, index=False)

    def obtener_datos(self, clave_archivo: str) -> List[Dict[str, Any]]:
        ruta = self.archivos[clave_archivo]
        if not os.path.exists(ruta): return []
        return pd.read_csv(ruta).to_dict(orient="records")

    def limpiar_archivo(self, clave_archivo: str) -> None:
        with self.lock:
            ruta = self.archivos[clave_archivo]
            pd.DataFrame(columns=self.columnas[clave_archivo]).to_csv(ruta, index=False)

# ==========================================
# 3. CAPA DE NEGOCIO Y LÓGICA ACADÉMICA
# ==========================================
class GestorAcademicoLMS:
    def __init__(self, repositorio: RepositorioDatosFIEE, seguridad: GestorSeguridadInstitucional):
        self.repo = repositorio
        self.seguridad = seguridad
        self.archivo_config = "examen_config.json"

    def crear_entorno_evaluacion(self, nombre_sala: str, docente: str, password: str) -> str:
        sala_formateada = nombre_sala.strip().upper()
        # 1. Registrar Sala
        registro = {"Sala": sala_formateada, "Creado": datetime.now().strftime("%Y-%m-%d %H:%M"), "Docente": docente}
        self.repo.guardar_registro("salas", registro)
        # 2. Registrar Credenciales del Docente
        self.seguridad.registrar_docente(docente, password, sala_formateada)
        return sala_formateada

    def verificar_existencia_sala(self, sala: str) -> bool:
        salas = self.repo.obtener_datos("salas")
        return any(s['Sala'].strip().upper() == sala.strip().upper() for s in salas)

    def matricular_alumno_examen(self, uid: str, nombre: str, sala: str) -> None:
        asist = {"ID": uid, "Nombre": nombre, "Sala": sala.upper(), "Estado": "EN EXAMEN", "Camara": "OK", "Inicio": datetime.now().strftime("%H:%M:%S")}
        self.repo.guardar_registro("asistencia", asist)

    def procesar_entrega_examen(self, uid: str, respuestas_json: str) -> None:
        data = {"ID": uid, "Respuestas": respuestas_json, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self.repo.guardar_registro("respuestas", data)
        self.repo.actualizar_estado("asistencia", uid, "Estado", "FINALIZADO")

    def guardar_configuracion_examen(self, tipo: str, contenido: str, sala: str) -> None:
        config = self.obtener_configuracion_general()
        config[sala] = {"tipo": tipo, "url": "", "preguntas": []}
        if tipo == "tradicional": 
            config[sala]["url"] = contenido
        elif tipo == "interactivo":
            try: config[sala]["preguntas"] = json.loads(contenido)
            except ValueError: pass
        with open(self.archivo_config, "w", encoding="utf-8") as f: json.dump(config, f)

    def obtener_configuracion_general(self) -> dict:
        try:
            with open(self.archivo_config, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: return {}

    def obtener_examen_por_sala(self, sala: str) -> dict:
        config = self.obtener_configuracion_general()
        return config.get(sala, {"tipo": "tradicional", "url": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg", "preguntas": []})

# ==========================================
# 4. CAPA DE ANÁLISIS E INTELIGENCIA
# ==========================================
class AnalizadorProctoring:
    def __init__(self, repositorio: RepositorioDatosFIEE):
        self.repo = repositorio

    def registrar_infraccion_ia(self, uid: str, nombre: str, sala: str, falta: str, img_b64: str, camara_activa: bool) -> None:
        timestamp = datetime.now().strftime("%H%M%S")
        ruta_imagen = f"evidencias/{uid}_{timestamp}.jpg"
        
        try:
            with open(ruta_imagen, "wb") as f: f.write(base64.b64decode(img_b64.split(",")[1]))
        except Exception: pass

        if not camara_activa:
            self.repo.actualizar_estado("asistencia", uid, "Camara", "BLOQUEADA")

        incidencia = {"Fecha": datetime.now().strftime("%H:%M:%S"), "ID": uid, "Nombre": nombre, "Sala": sala, "Falta": falta, "Ruta": ruta_imagen}
        self.repo.guardar_registro("db", incidencia)

    def generar_estadisticas_docente(self, sala_docente: str) -> Tuple[Dict[str, int], List, List, List]:
        """Filtra y genera estadísticas aislando los datos de la sala del docente actual."""
        asistencia_total = self.repo.obtener_datos("asistencia")
        incidencias_total = self.repo.obtener_datos("db")
        respuestas_crudas = self.repo.obtener_datos("respuestas")
        
        # Filtros de Aislamiento de Datos
        asistencia = [a for a in asistencia_total if a["Sala"] == sala_docente]
        incidencias = [i for i in incidencias_total if i["Sala"] == sala_docente]
        ids_sala = [a["ID"] for a in asistencia]
        respuestas_sala = [r for r in respuestas_crudas if r["ID"] in ids_sala]
        
        respuestas_procesadas = []
        for r in respuestas_sala:
            try: r['Detalle'] = json.loads(r['Respuestas'])
            except: r['Detalle'] = {"Formato": "Datos no procesables"}
            respuestas_procesadas.append(r)
        
        estadisticas = {
            "total_alumnos": len(asistencia),
            "activos": sum(1 for a in asistencia if a["Estado"] == "EN EXAMEN"),
            "camaras_tapadas": sum(1 for a in asistencia if a["Camara"] == "BLOQUEADA"),
            "total_alertas": len(incidencias)
        }
        return estadisticas, incidencias[::-1], asistencia[::-1], respuestas_procesadas[::-1]

    def purgar_evidencias(self) -> None:
        """Recolector de basura: limpia CSV y archivos físicos."""
        self.repo.limpiar_archivo("db")
        carpeta = "evidencias"
        for archivo in os.listdir(carpeta):
            if archivo.endswith(".jpg"):
                try: os.remove(os.path.join(carpeta, archivo))
                except Exception: pass

# ==========================================
# INICIALIZACIÓN DEL SISTEMA
# ==========================================
app = FastAPI(title="Proctoring System FIEE - Secure Edition")
# Middleware de Sesiones inyectado para seguridad de estado
app.add_middleware(SessionMiddleware, secret_key="proctoring_fiee_uni_2026_super_secure_key")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

# Inyección de dependencias
db_manager = RepositorioDatosFIEE()
security_manager = GestorSeguridadInstitucional()
lms = GestorAcademicoLMS(db_manager, security_manager)
auditoria_ia = AnalizadorProctoring(db_manager)

class ModeloTensorIA(BaseModel):
    uid: str; nombre: str; sala: str; tipo_falta: str; imagen_b64: str; camara_ok: bool

# ==========================================
# 5. ENRUTADOR PRINCIPAL HTTP (REST API)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def pagina_inicio(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "vista": "registro"})

@app.post("/crear_sala")
async def crear_sala(request: Request, docente: str = Form(...), nombre_sala: str = Form(...), password: str = Form(...)):
    sala_formateada = lms.crear_entorno_evaluacion(nombre_sala, docente, password)
    # Guardamos la identidad criptográfica en la sesión de la cookie
    request.session["docente"] = docente
    request.session["sala"] = sala_formateada
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/login_docente")
async def login_docente(request: Request, docente: str = Form(...), password: str = Form(...)):
    sala_asignada = security_manager.autenticar_docente(docente, password)
    if sala_asignada:
        request.session["docente"] = docente
        request.session["sala"] = sala_asignada
        return RedirectResponse(url="/dashboard", status_code=303)
    return HTMLResponse("<h1>❌ Credenciales Incorrectas o Docente no encontrado.</h1><a href='/'>Volver</a>", status_code=403)

@app.post("/ingresar_alumno")
async def ingresar_alumno(nombre: str = Form(...), uid: str = Form(...), sala: str = Form(...)):
    if not lms.verificar_existencia_sala(sala):
        return HTMLResponse(f"<h1>❌ Sala '{sala}' no encontrada. Verifica el código.</h1><a href='/'>Volver</a>", status_code=404)
    lms.matricular_alumno_examen(uid, nombre, sala)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala.upper()}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def vista_examen(request: Request, uid: str, nombre: str, sala: str):
    config_actual = lms.obtener_examen_por_sala(sala.upper())
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "examen", "uid": uid, "nombre": nombre, "sala": sala, "config": config_actual
    })

@app.post("/finalizar_evaluacion")
async def finalizar_evaluacion(uid: str = Form(...), respuestas: str = Form(...)):
    lms.procesar_entrega_examen(uid, respuestas)
    return templates.TemplateResponse("index.html", {"request": {}, "vista": "confirmacion"})

@app.get("/dashboard", response_class=HTMLResponse)
async def vista_dashboard(request: Request):
    # Verificación estricta de Middleware de Sesión
    if "docente" not in request.session:
        return RedirectResponse(url="/")
        
    docente = request.session["docente"]
    sala = request.session["sala"]
    
    stats, incidencias, asistencia, respuestas = auditoria_ia.generar_estadisticas_docente(sala)
    
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "dashboard", "stats": stats, 
        "incidencias": incidencias, "asistencia": asistencia, 
        "respuestas": respuestas, "docente": docente, "sala": sala
    })

@app.post("/configurar_lms")
async def configurar_lms(request: Request, tipo: str = Form(...), contenido: str = Form(...)):
    if "sala" in request.session:
        lms.guardar_configuracion_examen(tipo, contenido, request.session["sala"])
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/cambiar_password")
async def cambiar_password(request: Request, nueva_password: str = Form(...)):
    if "docente" in request.session:
        security_manager.actualizar_password(request.session["docente"], nueva_password)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/limpiar_auditoria")
async def limpiar_auditoria(request: Request):
    if "docente" in request.session:
        auditoria_ia.purgar_evidencias()
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear() # Destruye el token de sesión
    return RedirectResponse(url="/")

@app.post("/api/alerta_ia")
async def procesar_tensor_ia(alerta: ModeloTensorIA, bt: BackgroundTasks):
    bt.add_task(auditoria_ia.registrar_infraccion_ia, alerta.uid, alerta.nombre, alerta.sala, alerta.tipo_falta, alerta.imagen_b64, alerta.camara_ok)
    return {"estado": "ok"}

@app.get("/descargar_dataset")
async def descargar_dataset(request: Request):
    if "docente" in request.session and os.path.exists("database.csv"): 
        return FileResponse("database.csv", filename=f"Auditoria_{request.session['sala']}.csv")
    raise HTTPException(status_code=404)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
