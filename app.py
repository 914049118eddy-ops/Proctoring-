import os, base64, threading, uvicorn, pandas as pd, json
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="FIEE-UNI Proctoring System")
templates = Jinja2Templates(directory="templates")

# --- CONFIGURACIÓN DE RUTAS ---
DB_PATH = "database.csv"
ASISTENCIA_PATH = "asistencia.csv"
RESPUESTAS_PATH = "respuestas.csv"
CONFIG_EXAMEN = "config_examen.json"
CLAVE_DOCENTE = "uni2026"

# Inicialización de entorno para evitar "Status 1" en Render
for folder in ["evidencias", "static/js"]:
    os.makedirs(folder, exist_ok=True)

for file in [DB_PATH, ASISTENCIA_PATH, RESPUESTAS_PATH]:
    if not os.path.exists(file):
        pd.DataFrame().to_csv(file, index=False)

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

# --- CLASE DE NEGOCIO (POO) ---
class GestorExamen:
    """Clase encargada de la lógica del examen interactivo."""
    def __init__(self):
        self.config_default = {"tipo": "imagen", "contenido": "https://i.ibb.co/vzYp6YV/examen-fiee.jpg"}

    def obtener_config(self):
        if os.path.exists(CONFIG_EXAMEN):
            with open(CONFIG_EXAMEN, "r") as f: return json.load(f)
        return self.config_default

    def guardar_config(self, tipo, contenido):
        with open(CONFIG_EXAMEN, "w") as f:
            json.dump({"tipo": tipo, "contenido": contenido}, f)

gestor = GestorExamen()
csv_lock = threading.Lock()

# --- RUTAS ---
@app.get("/", response_class=HTMLResponse)
async def portal_index(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/ingresar")
async def ingresar(role: str = Form(...), nombre: str = Form(None), uid: str = Form(None), sala: str = Form(None), password: str = Form(None)):
    if role == "docente":
        if password == CLAVE_DOCENTE:
            return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)
        raise HTTPException(status_code=403, detail="Clave incorrecta")
    
    # Registro de Asistencia
    asist = {"ID": uid, "Nombre": nombre, "Sala": sala, "Estado": "ONLINE", "Inicio": datetime.now().strftime("%H:%M:%S")}
    with csv_lock:
        pd.DataFrame([asist]).to_csv(ASISTENCIA_PATH, mode='a', header=not os.path.exists(ASISTENCIA_PATH), index=False)
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen_view(request: Request, uid: str, nombre: str, sala: str):
    config = gestor.obtener_config()
    return templates.TemplateResponse("cliente.html", {
        "request": request, "uid": uid, "nombre": nombre, "sala": sala,
        "tipo": config["tipo"], "contenido": config["contenido"]
    })

@app.post("/finalizar")
async def finalizar_examen(uid: str = Form(...), respuestas: str = Form(...)):
    data = {"ID": uid, "Respuestas": respuestas, "Fin": datetime.now().strftime("%H:%M:%S")}
    with csv_lock:
        pd.DataFrame([data]).to_csv(RESPUESTAS_PATH, mode='a', index=False)
        df = pd.read_csv(ASISTENCIA_PATH)
        df.loc[df['ID'] == uid, 'Estado'] = "FINALIZADO"
        df.to_csv(ASISTENCIA_PATH, index=False)
    return HTMLResponse("<body style='font-family:sans-serif; text-align:center; padding-top:100px;'><h1>✅ Examen Enviado</h1><p>Los datos han sido recopilados.</p></body>")

@app.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE: return RedirectResponse("/")
    incidencias = pd.read_csv(DB_PATH).to_dict(orient="records") if os.path.exists(DB_PATH) else []
    asistencia = pd.read_csv(ASISTENCIA_PATH).to_dict(orient="records") if os.path.exists(ASISTENCIA_PATH) else []
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "incidencias": incidencias[::-1], "asistencia": asistencia[::-1], "password": password
    })

class Alerta(BaseModel):
    uid: str; nombre: str; sala: str; tipo_falta: str; imagen_b64: str; camara_ok: bool

@app.post("/api/alerta")
async def recibir_alerta(alerta: Alerta, bt: BackgroundTasks):
    def process():
        ts = datetime.now().strftime("%M%S")
        img_path = f"evidencias/{alerta.uid}_{ts}.jpg"
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(alerta.imagen_b64.split(",")[1]))
        reg = {"Fecha": datetime.now().strftime("%H:%M:%S"), "ID": alerta.uid, "Nombre": alerta.nombre, "Falta": alerta.tipo_falta, "Ruta": img_path}
        with csv_lock: pd.DataFrame([reg]).to_csv(DB_PATH, mode='a', header=not os.path.exists(DB_PATH), index=False)
    bt.add_task(process)
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
