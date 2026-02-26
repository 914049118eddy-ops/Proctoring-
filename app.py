import os, base64, threading, uvicorn, pandas as pd, json
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Tuple, Any

# ==========================================
# 1. CAPA DE DATOS Y PERSISTENCIA (POO) --
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
        self._inicializar_entorno()

    def _inicializar_entorno(self) -> None:
        """Configura el entorno de directorios y bases de datos iniciales."""
        for directorio in ["evidencias", "static/js"]: 
            os.makedirs(directorio, exist_ok=True)
            
        self._crear_csv_si_no_existe(self.archivos["db"], ["Fecha", "ID", "Nombre", "Sala", "Falta", "Ruta"])
        self._crear_csv_si_no_existe(self.archivos["asistencia"], ["ID", "Nombre", "Sala", "Estado", "Camara", "Inicio"])
        self._crear_csv_si_no_existe(self.archivos["respuestas"], ["ID", "Respuestas", "Fecha"])
        self._crear_csv_si_no_existe(self.archivos["salas"], ["Sala", "Creado"])

    def _crear_csv_si_no_existe(self, ruta: str, columnas: List[str]) -> None:
        if not os.path.exists(ruta) or os.stat(ruta).st_size == 0:
            pd.DataFrame(columns=columnas).to_csv(ruta, index=False)

    def guardar_registro(self, clave_archivo: str, registro: Dict[str, Any]) -> None:
        """Guarda un registro de forma concurrente y segura."""
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

# ==========================================
# 2. CAPA DE NEGOCIO Y LÓGICA ACADÉMICA
# ==========================================
class GestorAcademicoLMS:
    """Implementa las reglas de negocio de la Universidad."""
    def __init__(self, repositorio: RepositorioDatosFIEE):
        self.repo = repositorio
        self.archivo_config = "examen_config.json"
        self.config_base = {
            "tipo": "tradicional", 
            "url": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhLVm19tPx0AwLoM1jz5W4UkrN7e2gM8J23pk7kp7X0nliJ-SDQ79rd8s-fyoRZOmtO78ToP_lwaXCv_wXozQbcM08juHv5YzMAAePnVIk9BWG3hgGuCOeKidfyKMFTwOsyYHjf8FJwpWeF/s1600/FISICA-I-UNI-B.jpg", 
            "preguntas": []
        }

    def registrar_nueva_sala(self, nombre_sala: str) -> None:
        # Validación para no crear salas vacías
        if not nombre_sala or nombre_sala.strip() == "":
            return
        registro = {"Sala": nombre_sala.upper(), "Creado": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.repo.guardar_registro("salas", registro)

    def verificar_existencia_sala(self, sala: str) -> bool:
        salas = self.repo.obtener_datos("salas")
        # Comparación robusta
        return any(s['Sala'].strip().upper() == sala.strip().upper() for s in salas)

    def matricular_alumno_examen(self, uid: str, nombre: str, sala: str) -> None:
        asist = {"ID": uid, "Nombre": nombre, "Sala": sala.upper(), "Estado": "EN EXAMEN", "Camara": "OK", "Inicio": datetime.now().strftime("%H:%M:%S")}
        self.repo.guardar_registro("asistencia", asist)

    def procesar_entrega_examen(self, uid: str, respuestas_json: str) -> None:
        data = {"ID": uid, "Respuestas": respuestas_json, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self.repo.guardar_registro("respuestas", data)
        self.repo.actualizar_estado("asistencia", uid, "Estado", "FINALIZADO")

    def guardar_configuracion_docente(self, tipo: str, contenido: str) -> None:
        configuracion = {"tipo": tipo, "url": "", "preguntas": []}
        if tipo == "tradicional": 
            configuracion["url"] = contenido
        elif tipo == "interactivo":
            try: configuracion["preguntas"] = json.loads(contenido)
            except ValueError: print("Error: JSON de preguntas inválido.")
        with open(self.archivo_config, "w", encoding="utf-8") as f: 
            json.dump(configuracion, f)

    def obtener_configuracion_actual(self) -> Dict[str, Any]:
        try:
            with open(self.archivo_config, "r", encoding="utf-8") as f: return json.load(f)
        except Exception: 
            return self.config_base

# ==========================================
# 3. CAPA DE ANÁLISIS E INTELIGENCIA
# ==========================================
class AnalizadorProctoring:
    """Procesa auditorías, estadísticas y evidencias de IA."""
    def __init__(self, repositorio: RepositorioDatosFIEE):
        self.repo = repositorio

    def registrar_infraccion_ia(self, uid: str, nombre: str, sala: str, falta: str, img_b64: str, camara_activa: bool) -> None:
        timestamp = datetime.now().strftime("%H%M%S")
        ruta_imagen = f"evidencias/{uid}_{timestamp}.jpg"
        
        try:
            with open(ruta_imagen, "wb") as f:
                f.write(base64.b64decode(img_b64.split(",")[1]))
        except Exception as error_io:
            print(f"Error de E/S al guardar evidencia: {error_io}")

        if not camara_activa:
            self.repo.actualizar_estado("asistencia", uid, "Camara", "BLOQUEADA")

        incidencia = {
            "Fecha": datetime.now().strftime("%H:%M:%S"),
            "ID": uid, "Nombre": nombre, "Sala": sala, "Falta": falta, "Ruta": ruta_imagen
        }
        self.repo.guardar_registro("db", incidencia)

    def generar_estadisticas_dashboard(self) -> Tuple[Dict[str, int], List, List, List, List]:
        asistencia = self.repo.obtener_datos("asistencia")
        incidencias = self.repo.obtener_datos("db")
        salas = self.repo.obtener_datos("salas")
        respuestas_crudas = self.repo.obtener_datos("respuestas")
        
        respuestas_procesadas = []
        for r in respuestas_crudas:
            try:
                r['Detalle'] = json.loads(r['Respuestas'])
            except:
                r['Detalle'] = {"Formato": "Datos no procesables"}
            respuestas_procesadas.append(r)
        
        estadisticas = {
            "total_alumnos": len(asistencia),
            "activos": sum(1 for a in asistencia if a["Estado"] == "EN EXAMEN"),
            "camaras_tapadas": sum(1 for a in asistencia if a["Camara"] == "BLOQUEADA"),
            "total_alertas": len(incidencias)
        }
        
        return estadisticas, incidencias[::-1], asistencia[::-1], salas, respuestas_procesadas[::-1]

# ==========================================
# INICIALIZACIÓN DEL SISTEMA
# ==========================================
app = FastAPI(title="Proctoring System FIEE", description="Arquitectura de 3 capas Orientada a Objetos")
templates = Jinja2Templates(directory="templates")

CLAVE_INSTITUCIONAL = "uni2026"
db_manager = RepositorioDatosFIEE()
lms = GestorAcademicoLMS(db_manager)
auditoria_ia = AnalizadorProctoring(db_manager)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

class ModeloTensorIA(BaseModel):
    uid: str; nombre: str; sala: str; tipo_falta: str; imagen_b64: str; camara_ok: bool

# ==========================================
# 4. ENRUTADOR PRINCIPAL (Vista Única HTML)
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def pagina_inicio(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "vista": "registro"})

@app.post("/procesar_acceso")
async def procesar_acceso(role: str = Form(...), nombre: str = Form(None), uid: str = Form(None), sala: str = Form(None), password: str = Form(None)):
    if role == "docente":
        if password == CLAVE_INSTITUCIONAL:
            return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)
        return HTMLResponse("<h1>❌ Credenciales Docentes Incorrectas</h1><a href='/'>Volver</a>", status_code=403)
    
    if not lms.verificar_existencia_sala(sala):
        return HTMLResponse(f"<h1>❌ Sala '{sala}' no encontrada. Verifica el código.</h1><a href='/'>Volver</a>", status_code=404)

    lms.matricular_alumno_examen(uid, nombre, sala)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala}", status_code=303)

# ---> AQUÍ ESTÁ LA RUTA QUE FALTABA <---
@app.post("/crear_sala")
async def crear_sala_nueva(nombre_sala: str = Form(...), password: str = Form(...)):
    """Endpoint para que el profesor registre nuevas salas de examen."""
    if password == CLAVE_INSTITUCIONAL:
        lms.registrar_nueva_sala(nombre_sala)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def vista_examen(request: Request, uid: str, nombre: str, sala: str):
    config_actual = lms.obtener_configuracion_actual()
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "examen", 
        "uid": uid, "nombre": nombre, "sala": sala, "config": config_actual
    })

@app.post("/finalizar_evaluacion")
async def finalizar_evaluacion(uid: str = Form(...), respuestas: str = Form(...)):
    lms.procesar_entrega_examen(uid, respuestas)
    return templates.TemplateResponse("index.html", {"request": {}, "vista": "confirmacion"})

@app.post("/configurar_lms")
async def configurar_lms(tipo: str = Form(...), contenido: str = Form(...), password: str = Form(...)):
    if password == CLAVE_INSTITUCIONAL: 
        lms.guardar_configuracion_docente(tipo, contenido)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def vista_dashboard(request: Request, password: str = None):
    if password != CLAVE_INSTITUCIONAL: return RedirectResponse("/")
    
    stats, incidencias, asistencia, salas, respuestas = auditoria_ia.generar_estadisticas_dashboard()
    
    return templates.TemplateResponse("index.html", {
        "request": request, "vista": "dashboard", "stats": stats, 
        "incidencias": incidencias, "asistencia": asistencia, 
        "salas": salas, "respuestas": respuestas, "password": password
    })

@app.post("/api/alerta_ia")
async def procesar_tensor_ia(alerta: ModeloTensorIA, bt: BackgroundTasks):
    bt.add_task(auditoria_ia.registrar_infraccion_ia, alerta.uid, alerta.nombre, alerta.sala, alerta.tipo_falta, alerta.imagen_b64, alerta.camara_ok)
    return {"estado": "Procesado correctamente por el Backend"}

@app.get("/descargar_dataset")
async def descargar_dataset(password: str = None):
    if password == CLAVE_INSTITUCIONAL and os.path.exists("database.csv"): 
        return FileResponse("database.csv", filename="Auditoria_Proctoring_FIEE.csv")
    raise HTTPException(status_code=404)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))


