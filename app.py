import os, base64, threading, uvicorn, pandas as pd, json
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Persistencia de datos
DB_PATH = "database.csv"
ASISTENCIA_PATH = "asistencia.csv"
PREGUNTAS_PATH = "preguntas.json"  # Aquí guardamos el examen interactivo
RESPUESTAS_PATH = "respuestas.csv"
CLAVE_DOCENTE = "uni2026"
csv_lock = threading.Lock()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

class Alerta(BaseModel):
    uid: str; nombre: str; sala: str; tipo_falta: str; imagen_b64: str; camara_ok: bool

# --- LÓGICA DE EXAMEN INTERACTIVO ---

@app.post("/configurar_examen")
async def configurar(tipo: str = Form(...), contenido: str = Form(...), password: str = Form(...)):
    if password != CLAVE_DOCENTE: return HTMLResponse("No autorizado", status_code=403)
    # contenido será un JSON con las preguntas o un link de imagen
    data = {"tipo": tipo, "contenido": contenido}
    with open(PREGUNTAS_PATH, "w") as f:
        json.dump(data, f)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.post("/enviar_respuestas")
async def recibir_respuestas(uid: str = Form(...), r_json: str = Form(...)):
    """Guarda las respuestas del alumno al finalizar."""
    resp = {"ID": uid, "Respuestas": r_json, "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M")}
    with csv_lock:
        pd.DataFrame([resp]).to_csv(RESPUESTAS_PATH, mode='a', header=not os.path.exists(RESPUESTAS_PATH), index=False)
    # Marcar como finalizado en asistencia
    df = pd.read_csv(ASISTENCIA_PATH)
    df.loc[df['ID'] == uid, 'Estado'] = "FINALIZADO"
    df.to_csv(ASISTENCIA_PATH, index=False)
    return HTMLResponse("<h1>✅ Examen Enviado Correctamente</h1>")

# --- RUTAS DE ACCESO ---

@app.get("/examen", response_class=HTMLResponse)
async def examen(request: Request, uid: str, nombre: str, sala: str):
    # Cargar la configuración del examen
    config = {"tipo": "imagen", "contenido": "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEhLVm19tPx0AwLoM1jz5W4UkrN7e2gM8J23pk7kp7X0nliJ-SDQ79rd8s-fyoRZOmtO78ToP_lwaXCv_wXozQbcM08juHv5YzMAAePnVIk9BWG3hgGuCOeKidfyKMFTwOsyYHjf8FJwpWeF/s1600/FISICA-I-UNI-B.jpg"}
    if os.path.exists(PREGUNTAS_PATH):
        with open(PREGUNTAS_PATH, "r") as f: config = json.load(f)
    
    return templates.TemplateResponse("cliente.html", {
        "request": request, "uid": uid, "nombre": nombre, "sala": sala, 
        "tipo_examen": config["tipo"], "contenido": config["contenido"]
    })

# ... (Mantén tus rutas de /dashboard, /api/alerta y /ingresar igual que antes)
