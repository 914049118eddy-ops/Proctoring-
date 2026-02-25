import os, base64, threading, uvicorn, pandas as pd, json
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- PERSISTENCIA Y CONFIGURACIÓN ---
DB_PATH = "database.csv"
ASISTENCIA_PATH = "asistencia.csv"
RESPUESTAS_PATH = "respuestas.csv"
EXAMEN_CONFIG = "examen_config.json"
CLAVE_DOCENTE = "uni2026"

for f in ["evidencias", "static/js"]: os.makedirs(f, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

# --- CLASE DE LÓGICA DE NEGOCIO (POO EN PYTHON) ---
class MotorExamen:
    """Gestiona la creación y recopilación de exámenes tipo LMS."""
    def __init__(self):
        self.default = {"tipo": "tradicional", "url": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg", "preguntas": []}

    def cargar(self):
        if os.path.exists(EXAMEN_CONFIG):
            with open(EXAMEN_CONFIG, "r", encoding="utf-8") as f: return json.load(f)
        return self.default

    def guardar(self, tipo, contenido):
        data = {"tipo": tipo, "url": contenido if tipo == "tradicional" else "", 
                "preguntas": json.loads(contenido) if tipo == "interactivo" else []}
        with open(EXAMEN_CONFIG, "w", encoding="utf-8") as f: json.dump(data, f)

motor = MotorExamen()
csv_lock = threading.Lock()

# --- RUTAS DEL PORTAL ---

@app.get("/", response_class=HTMLResponse)
async def portal(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/ingresar")
async def ingresar(role: str = Form(...), nombre: str = Form(None), uid: str = Form(None), sala: str = Form(None), password: str = Form(None)):
    if role == "docente" and password == CLAVE_DOCENTE:
        return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)
    
    # Registro de Asistencia en Python
    asist = {"ID": uid, "Nombre": nombre, "Sala": sala, "Estado": "EN EXAMEN", "Inicio": datetime.now().strftime("%H:%M:%S")}
    with csv_lock:
        pd.DataFrame([asist]).to_csv(ASISTENCIA_PATH, mode='a', header=not os.path.exists(ASISTENCIA_PATH), index=False)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen_view(request: Request, uid: str, nombre: str, sala: str):
    config = motor.cargar()
    return templates.TemplateResponse("cliente.html", {
        "request": request, "uid": uid, "nombre": nombre, "sala": sala, "config": config
    })

@app.post("/enviar_examen")
async def finalizar(uid: str = Form(...), respuestas: str = Form(...)):
    # Python procesa y ordena los resultados finales
    data = {"ID": uid, "Respuestas": respuestas, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    with csv_lock:
        pd.DataFrame([data]).to_csv(RESPUESTAS_PATH, mode='a', header=not os.path.exists(RESPUESTAS_PATH), index=False)
        # Actualizar estado a Finalizado
        df = pd.read_csv(ASISTENCIA_PATH)
        df.loc[df['ID'] == uid, 'Estado'] = "FINALIZADO"
        df.to_csv(ASISTENCIA_PATH, index=False)
    return templates.TemplateResponse("confirmacion.html", {"request": {"nada": ""}}) # Página de confirmación

@app.post("/configurar_examen")
async def configurar(tipo: str = Form(...), contenido: str = Form(...), password: str = Form(...)):
    if password == CLAVE_DOCENTE: motor.guardar(tipo, contenido)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

# ... (Rutas de /dashboard y /api/alerta se mantienen igual)
