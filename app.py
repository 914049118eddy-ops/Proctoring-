import os, base64, threading, uvicorn, pandas as pd, json
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ==========================================
# 1. CAPA DE DATOS (Persistencia Segura)
# ==========================================
class RepositorioDatos:
    """Encapsula el acceso a los archivos físicos asegurando thread-safety (POO)."""
    def __init__(self):
        self.lock = threading.Lock()
        self._preparar_entorno()

    def _preparar_entorno(self):
        # Crea carpetas si no existen
        for d in ["evidencias", "static/js"]: 
            os.makedirs(d, exist_ok=True)
        # Inicializa CSVs con encabezados
        self._init_csv("database.csv", ["Fecha", "ID", "Nombre", "Sala", "Falta", "Ruta"])
        self._init_csv("asistencia.csv", ["ID", "Nombre", "Sala", "Estado", "Camara", "Inicio"])
        self._init_csv("respuestas.csv", ["ID", "Respuestas", "Fecha"])
        self._init_csv("salas.csv", ["Sala", "Creado"])

    def _init_csv(self, path: str, cols: list):
        if not os.path.exists(path) or os.stat(path).st_size == 0:
            pd.DataFrame(columns=cols).to_csv(path, index=False)

    def insertar_registro(self, archivo: str, registro: dict):
        with self.lock:
            pd.DataFrame([registro]).to_csv(archivo, mode='a', header=False, index=False)

    def actualizar_campo(self, archivo: str, id_valor: str, campo: str, nuevo_valor: str):
        with self.lock:
            df = pd.read_csv(archivo)
            df.loc[df['ID'] == id_valor, campo] = nuevo_valor
            df.to_csv(archivo, index=False)

    def obtener_todos(self, archivo: str) -> list:
        if not os.path.exists(archivo): return []
        return pd.read_csv(archivo).to_dict(orient="records")

# ==========================================
# 2. CAPA DE NEGOCIO (Lógica Académica)
# ==========================================
# Reemplaza solo la clase SistemaLMS y la ruta /dashboard en tu app.py actual

class SistemaLMS:
    """Maneja la lógica de negocio académica: Salas, Asistencia y Exámenes."""
    def __init__(self, repo: RepositorioDatos):
        self.repo = repo
        self.config_file = "examen_config.json"
        self.default_config = {"tipo": "tradicional", "url": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg", "preguntas": []}

    # ... (Mantén tus métodos crear_sala, validar_sala, registrar_ingreso, etc. iguales) ...

    def crear_sala(self, nombre_sala: str):
        registro = {"Sala": nombre_sala, "Creado": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self.repo.insertar_registro("salas.csv", registro)

    def validar_sala(self, sala: str) -> bool:
        salas = self.repo.obtener_todos("salas.csv")
        return any(s['Sala'] == sala for s in salas)

    def registrar_ingreso(self, uid: str, nombre: str, sala: str):
        asist = {"ID": uid, "Nombre": nombre, "Sala": sala, "Estado": "EN EXAMEN", "Camara": "OK", "Inicio": datetime.now().strftime("%H:%M:%S")}
        self.repo.insertar_registro("asistencia.csv", asist)

    def finalizar_examen(self, uid: str, respuestas: str):
        data = {"ID": uid, "Respuestas": respuestas, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self.repo.insertar_registro("respuestas.csv", data)
        self.repo.actualizar_campo("asistencia.csv", uid, "Estado", "FINALIZADO")

    def configurar_examen(self, tipo: str, contenido: str):
        data = {"tipo": tipo, "url": "", "preguntas": []}
        if tipo == "tradicional": data["url"] = contenido
        elif tipo == "interactivo":
            try: data["preguntas"] = json.loads(contenido)
            except: pass
        with open(self.config_file, "w", encoding="utf-8") as f: json.dump(data, f)

    def cargar_configuracion(self) -> dict:
        try:
            with open(self.config_file, "r", encoding="utf-8") as f: return json.load(f)
        except: return self.default_config

    def obtener_estadisticas(self):
        asistencia = self.repo.obtener_todos("asistencia.csv")
        incidencias = self.repo.obtener_todos("database.csv")
        salas = self.repo.obtener_todos("salas.csv")
        respuestas_crudas = self.repo.obtener_todos("respuestas.csv")
        
        # Procesamos las respuestas JSON a diccionarios de Python para la plantilla HTML
        respuestas_formateadas = []
        for r in respuestas_crudas:
            try:
                res_dict = json.loads(r['Respuestas'])
                # Mapeamos para que se vea ordenado
                r['Detalle'] = res_dict
                respuestas_formateadas.append(r)
            except:
                r['Detalle'] = {"Error": "No se pudo decodificar"}
                respuestas_formateadas.append(r)
        
        stats = {
            "total": len(asistencia),
            "online": sum(1 for a in asistencia if a["Estado"] == "EN EXAMEN"),
            "bloqueados": sum(1 for a in asistencia if a["Camara"] == "BLOQUEADA"),
            "alertas": len(incidencias)
        }
        return stats, incidencias, asistencia, salas, respuestas_formateadas

# ----- EN LA SECCIÓN DE RUTAS HTTP -----
@app.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE: return RedirectResponse("/")
    
    stats, incidencias, asistencia, salas, respuestas = sistema_lms.obtener_estadisticas()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "stats": stats, "incidencias": incidencias[::-1], 
        "asistencia": asistencia[::-1], "salas": salas, "password": password,
        "respuestas": respuestas[::-1] # Pasamos las respuestas ordenadas de la más reciente a la antigua
    })

# ==========================================
# 3. CAPA DE NEGOCIO (Proctoring e IA)
# ==========================================
class MotorProctoring:
    """Procesa las evidencias y penalizaciones enviadas por la IA."""
    def __init__(self, repo: RepositorioDatos):
        self.repo = repo

    def procesar_incidente(self, uid, nombre, sala, tipo_falta, imagen_b64, camara_ok):
        ts = datetime.now().strftime("%H%M%S")
        img_path = f"evidencias/{uid}_{ts}.jpg"
        
        # Guardar imagen (decodificando base64)
        try:
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(imagen_b64.split(",")[1]))
        except Exception as e:
            print(f"Error guardando evidencia: {e}")

        # Penalizar en asistencia si tapan la cámara
        if not camara_ok:
            self.repo.actualizar_campo("asistencia.csv", uid, "Camara", "BLOQUEADA")

        # Registrar la falta en la base de datos
        reg = {"Fecha": datetime.now().strftime("%H:%M:%S"), "ID": uid, "Nombre": nombre, "Sala": sala, "Falta": tipo_falta, "Ruta": img_path}
        self.repo.insertar_registro("database.csv", reg)

# ==========================================
# INICIALIZACIÓN DE OBJETOS (Inyección de Dependencias)
# ==========================================
app = FastAPI(title="Proctoring POO - FIEE UNI")
templates = Jinja2Templates(directory="templates")

CLAVE_DOCENTE = "uni2026"
# Instanciamos nuestras clases
repo_db = RepositorioDatos()
sistema_lms = SistemaLMS(repo_db)
motor_ia = MotorProctoring(repo_db)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

class ModeloAlerta(BaseModel):
    uid: str; nombre: str; sala: str; tipo_falta: str; imagen_b64: str; camara_ok: bool

# ==========================================
# 4. CAPA DE CONTROLADORES (Rutas HTTP FastAPI)
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def portal(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/crear_sala")
async def crear_sala(nombre_sala: str = Form(...), password: str = Form(...)):
    if password != CLAVE_DOCENTE: return HTMLResponse("No autorizado", status_code=403)
    sistema_lms.crear_sala(nombre_sala)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.post("/ingresar")
async def ingresar(role: str = Form(...), nombre: str = Form(None), uid: str = Form(None), sala: str = Form(None), password: str = Form(None)):
    if role == "docente":
        if password == CLAVE_DOCENTE: return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)
        return HTMLResponse("<h1>❌ Clave incorrecta</h1><a href='/'>Volver</a>", status_code=403)
    
    if not sistema_lms.validar_sala(sala):
        return HTMLResponse(f"<h1>❌ La sala '{sala}' no existe.</h1><a href='/'>Volver</a>", status_code=404)

    sistema_lms.registrar_ingreso(uid, nombre, sala)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen_view(request: Request, uid: str, nombre: str, sala: str):
    config = sistema_lms.cargar_configuracion()
    return templates.TemplateResponse("cliente.html", {
        "request": request, "uid": uid, "nombre": nombre, "sala": sala, "config": config
    })

@app.post("/finalizar")
async def finalizar_examen(uid: str = Form(...), respuestas: str = Form(...)):
    sistema_lms.finalizar_examen(uid, respuestas)
    html_confirmacion = """
        <body style='font-family:sans-serif; background:#f4f7f6; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;'>
            <div style='background:white; padding:40px; border-radius:15px; box-shadow:0 5px 15px rgba(0,0,0,0.1); text-align:center;'>
                <h1 style='color:#28a745; margin-bottom:10px;'>✅ Examen Enviado</h1>
                <p style='color:#555;'>Tus respuestas han sido registradas en el sistema de la FIEE.</p>
                <button onclick='location.href=\"/\"' style='background:#800000; color:white; border:none; padding:12px 25px; border-radius:6px; cursor:pointer; margin-top:20px; font-weight:bold;'>Volver al Inicio</button>
            </div>
        </body>
    """
    return HTMLResponse(html_confirmacion)

@app.post("/configurar_examen")
async def configurar(tipo: str = Form(...), contenido: str = Form(...), password: str = Form(...)):
    if password == CLAVE_DOCENTE: 
        sistema_lms.configurar_examen(tipo, contenido)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE: return RedirectResponse("/")
    
    stats, incidencias, asistencia, salas = sistema_lms.obtener_estadisticas()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "stats": stats, "incidencias": incidencias[::-1], 
        "asistencia": asistencia[::-1], "salas": salas, "password": password
    })

@app.post("/api/alerta")
async def recibir_alerta(alerta: ModeloAlerta, bt: BackgroundTasks):
    # Procesamos la alerta en segundo plano usando nuestra clase POO
    bt.add_task(motor_ia.procesar_incidente, alerta.uid, alerta.nombre, alerta.sala, alerta.tipo_falta, alerta.imagen_b64, alerta.camara_ok)
    return {"status": "ok"}

@app.get("/descargar_reporte")
async def reporte(password: str = None):
    if password == CLAVE_DOCENTE and os.path.exists("database.csv"): 
        return FileResponse("database.csv", filename="Reporte_FIEE.csv")
    raise HTTPException(status_code=404)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)

