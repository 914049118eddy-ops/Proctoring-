import os, base64, threading, uvicorn, pandas as pd, json
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="FIEE-UNI Proctoring System")
templates = Jinja2Templates(directory="templates")

# --- PERSISTENCIA Y CONFIGURACIÓN ---
DB_PATH = "database.csv"
ASISTENCIA_PATH = "asistencia.csv"
RESPUESTAS_PATH = "respuestas.csv"
SALAS_PATH = "salas.csv"
EXAMEN_CONFIG = "examen_config.json"
CLAVE_DOCENTE = "uni2026"

# Asegurar directorios
for f in ["evidencias", "static/js"]: 
    os.makedirs(f, exist_ok=True)

# Asegurar archivos CSV con encabezados (Evita Error 500)
def init_csv(path, columns):
    if not os.path.exists(path) or os.stat(path).st_size == 0:
        pd.DataFrame(columns=columns).to_csv(path, index=False)

init_csv(DB_PATH, ["Fecha", "ID", "Nombre", "Sala", "Falta", "Ruta"])
init_csv(ASISTENCIA_PATH, ["ID", "Nombre", "Sala", "Estado", "Camara", "Inicio"])
init_csv(RESPUESTAS_PATH, ["ID", "Respuestas", "Fecha"])
init_csv(SALAS_PATH, ["Sala", "Creado"])

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

# --- CLASE DE LÓGICA DE NEGOCIO (POO EN PYTHON) ---
class MotorExamen:
    """Gestiona la creación y recopilación de exámenes tipo LMS."""
    def __init__(self):
        self.default = {
            "tipo": "tradicional", 
            "url": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhLVm19tPx0AwLoM1jz5W4UkrN7e2gM8J23pk7kp7X0nliJ-SDQ79rd8s-fyoRZOmtO78ToP_lwaXCv_wXozQbcM08juHv5YzMAAePnVIk9BWG3hgGuCOeKidfyKMFTwOsyYHjf8FJwpWeF/s1600/FISICA-I-UNI-B.jpg", 
            "preguntas": []
        }

    def cargar(self):
        if os.path.exists(EXAMEN_CONFIG):
            try:
                with open(EXAMEN_CONFIG, "r", encoding="utf-8") as f: return json.load(f)
            except json.JSONDecodeError:
                return self.default
        return self.default

    def guardar(self, tipo, contenido):
        data = {"tipo": tipo, "url": "", "preguntas": []}
        if tipo == "tradicional":
            data["url"] = contenido
        elif tipo == "interactivo":
            try:
                data["preguntas"] = json.loads(contenido)
            except json.JSONDecodeError:
                pass # Manejo de error si el profe escribe mal el JSON
                
        with open(EXAMEN_CONFIG, "w", encoding="utf-8") as f: json.dump(data, f)

motor = MotorExamen()
csv_lock = threading.Lock()

# --- RUTAS DEL PORTAL ---

@app.get("/", response_class=HTMLResponse)
async def portal(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/crear_sala")
async def crear_sala(nombre_sala: str = Form(...), password: str = Form(...)):
    if password != CLAVE_DOCENTE: return HTMLResponse("No autorizado", status_code=403)
    nueva_sala = {"Sala": nombre_sala, "Creado": datetime.now().strftime("%Y-%m-%d %H:%M")}
    with csv_lock:
        pd.DataFrame([nueva_sala]).to_csv(SALAS_PATH, mode='a', header=False, index=False)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.post("/ingresar")
async def ingresar(role: str = Form(...), nombre: str = Form(None), uid: str = Form(None), sala: str = Form(None), password: str = Form(None)):
    if role == "docente" and password == CLAVE_DOCENTE:
        return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)
    elif role == "docente":
         return HTMLResponse("<h1>❌ Clave incorrecta</h1><a href='/'>Volver</a>", status_code=403)
    
    # Validar que la sala exista
    if os.path.exists(SALAS_PATH):
        df_salas = pd.read_csv(SALAS_PATH)
        if sala not in df_salas['Sala'].values:
            return HTMLResponse(f"<h1>❌ La sala '{sala}' no existe. Pide el código al profesor.</h1><a href='/'>Volver</a>")

    # Registro de Asistencia
    asist = {"ID": uid, "Nombre": nombre, "Sala": sala, "Estado": "EN EXAMEN", "Camara": "OK", "Inicio": datetime.now().strftime("%H:%M:%S")}
    with csv_lock:
        pd.DataFrame([asist]).to_csv(ASISTENCIA_PATH, mode='a', header=False, index=False)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen_view(request: Request, uid: str, nombre: str, sala: str):
    config = motor.cargar()
    return templates.TemplateResponse("cliente.html", {
        "request": request, "uid": uid, "nombre": nombre, "sala": sala, "config": config
    })

@app.post("/finalizar")
async def finalizar_examen(uid: str = Form(...), respuestas: str = Form(...)):
    # Guardar respuestas
    data = {"ID": uid, "Respuestas": respuestas, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with csv_lock:
        pd.DataFrame([data]).to_csv(RESPUESTAS_PATH, mode='a', header=False, index=False)
        # Actualizar estado a Finalizado
        if os.path.exists(ASISTENCIA_PATH):
            df = pd.read_csv(ASISTENCIA_PATH)
            df.loc[df['ID'] == uid, 'Estado'] = "FINALIZADO"
            df.to_csv(ASISTENCIA_PATH, index=False)
            
    # Mensaje de confirmación en HTML puro
    return HTMLResponse("""
        <body style='font-family:sans-serif; background:#f4f7f6; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;'>
            <div style='background:white; padding:40px; border-radius:15px; box-shadow:0 5px 15px rgba(0,0,0,0.1); text-align:center;'>
                <h1 style='color:#28a745; margin-bottom:10px;'>✅ Examen Enviado</h1>
                <p style='color:#555;'>Tus respuestas han sido registradas en el sistema de la FIEE.</p>
                <button onclick='location.href=\"/\"' style='background:#800000; color:white; border:none; padding:12px 25px; border-radius:6px; cursor:pointer; margin-top:20px; font-weight:bold;'>Volver al Inicio</button>
            </div>
        </body>
    """)

@app.post("/configurar_examen")
async def configurar(tipo: str = Form(...), contenido: str = Form(...), password: str = Form(...)):
    if password == CLAVE_DOCENTE: 
        motor.guardar(tipo, contenido)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE: return RedirectResponse("/")
    
    incidencias = pd.read_csv(DB_PATH).to_dict(orient="records") if os.path.exists(DB_PATH) else []
    asistencia = pd.read_csv(ASISTENCIA_PATH).to_dict(orient="records") if os.path.exists(ASISTENCIA_PATH) else []
    salas = pd.read_csv(SALAS_PATH).to_dict(orient="records") if os.path.exists(SALAS_PATH) else []
    
    # Calcular estadísticas
    stats = {
        "total": len(asistencia),
        "online": sum(1 for a in asistencia if a["Estado"] == "EN EXAMEN"),
        "bloqueados": sum(1 for a in asistencia if a["Camara"] == "BLOQUEADA"),
        "alertas": len(incidencias)
    }
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "stats": stats, "incidencias": incidencias[::-1], 
        "asistencia": asistencia[::-1], "salas": salas, "password": password
    })

class Alerta(BaseModel):
    uid: str; nombre: str; sala: str; tipo_falta: str; imagen_b64: str; camara_ok: bool

@app.post("/api/alerta")
async def recibir_alerta(alerta: Alerta, bt: BackgroundTasks):
    def process():
        ts = datetime.now().strftime("%H%M%S")
        img_path = f"evidencias/{alerta.uid}_{ts}.jpg"
        
        # Guardar imagen
        try:
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(alerta.imagen_b64.split(",")[1]))
        except Exception as e:
            print("Error guardando imagen:", e)
            
        # Actualizar cámara si falló
        if not alerta.camara_ok:
            with csv_lock:
                df = pd.read_csv(ASISTENCIA_PATH)
                df.loc[df['ID'] == alerta.uid, 'Camara'] = "BLOQUEADA"
                df.to_csv(ASISTENCIA_PATH, index=False)
                
        # Registrar incidencia
        reg = {"Fecha": datetime.now().strftime("%H:%M:%S"), "ID": alerta.uid, "Nombre": alerta.nombre, "Sala": alerta.sala, "Falta": alerta.tipo_falta, "Ruta": img_path}
        with csv_lock: 
            pd.DataFrame([reg]).to_csv(DB_PATH, mode='a', header=False, index=False)
            
    bt.add_task(process)
    return {"status": "ok"}

@app.get("/descargar_reporte")
async def reporte(password: str = None):
    if password == CLAVE_DOCENTE and os.path.exists(DB_PATH): 
        return FileResponse(DB_PATH, filename="Reporte_FIEE.csv")
    raise HTTPException(status_code=404)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
