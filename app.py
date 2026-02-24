import os, base64, threading, uvicorn, pandas as pd
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Configuración de Archivos
DB_PATH = "database.csv"
SALAS_PATH = "salas.csv"
ASISTENCIA_PATH = "asistencia.csv"
CLAVE_DOCENTE = "uni2026"
os.makedirs("evidencias", exist_ok=True)
csv_lock = threading.Lock()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

class Alerta(BaseModel):
    uid: str; nombre: str; sala: str; tipo_falta: str; imagen_b64: str; camara_ok: bool

# --- LÓGICA DE ACCESO ---

@app.get("/", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/crear_sala")
async def crear_sala(nombre_sala: str = Form(...), password: str = Form(...)):
    if password != CLAVE_DOCENTE: return HTMLResponse("No autorizado", status_code=403)
    nueva = {"Sala": nombre_sala, "Creado": datetime.now().strftime("%Y-%m-%d %H:%M")}
    with csv_lock:
        pd.DataFrame([nueva]).to_csv(SALAS_PATH, mode='a', header=not os.path.exists(SALAS_PATH), index=False)
    return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)

@app.post("/ingresar")
async def ingresar(role: str = Form(...), nombre: str = Form(None), uid: str = Form(None), sala: str = Form(None), password: str = Form(None)):
    if role == "docente":
        if password == CLAVE_DOCENTE: return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)
        return HTMLResponse("Error de credenciales", status_code=403)
    
    # Validar Sala
    if not os.path.exists(SALAS_PATH) or sala not in pd.read_csv(SALAS_PATH)['Sala'].values:
        return HTMLResponse("<h1>❌ La sala no existe.</h1><a href='/'>Volver</a>")

    # Registro de Asistencia
    asist = {"ID": uid, "Nombre": nombre, "Sala": sala, "Estado": "ONLINE", "Camara": "OK", "Fecha": datetime.now().strftime("%H:%M:%S")}
    with csv_lock:
        pd.DataFrame([asist]).to_csv(ASISTENCIA_PATH, mode='a', header=not os.path.exists(ASISTENCIA_PATH), index=False)
    
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&sala={sala}", status_code=303)

@app.get("/finalizar_examen")
async def finalizar(uid: str):
    if os.path.exists(ASISTENCIA_PATH):
        with csv_lock:
            df = pd.read_csv(ASISTENCIA_PATH)
            df.loc[df['ID'] == uid, 'Estado'] = "FINALIZADO"
            df.to_csv(ASISTENCIA_PATH, index=False)
    return HTMLResponse("<body style='font-family:sans-serif; text-align:center; padding-top:50px;'><h1>✅ Examen Finalizado</h1><p>Tu registro ha sido guardado.</p></body>")

# --- DASHBOARD Y API ---

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE: return RedirectResponse(url="/")
    inc = pd.read_csv(DB_PATH).to_dict(orient="records") if os.path.exists(DB_PATH) else []
    asist = pd.read_csv(ASISTENCIA_PATH).to_dict(orient="records") if os.path.exists(ASISTENCIA_PATH) else []
    salas = pd.read_csv(SALAS_PATH).to_dict(orient="records") if os.path.exists(SALAS_PATH) else []
    return templates.TemplateResponse("dashboard.html", {"request": request, "incidencias": inc[::-1], "asistencia": asist[::-1], "salas": salas})

@app.post("/api/alerta")
async def api_alerta(alerta: Alerta, bt: BackgroundTasks):
    def process():
        if not alerta.camara_ok:
            df = pd.read_csv(ASISTENCIA_PATH)
            df.loc[df['ID'] == alerta.uid, 'Camara'] = "BLOQUEADA"
            df.to_csv(ASISTENCIA_PATH, index=False)
        
        ts = datetime.now().strftime("%M%S")
        path = f"evidencias/{alerta.uid}_{ts}.jpg"
        with open(path, "wb") as f: f.write(base64.b64decode(alerta.imagen_b64.split(",")[1]))
        reg = {"Fecha": datetime.now().strftime("%H:%M:%S"), "ID": alerta.uid, "Nombre": alerta.nombre, "Sala": alerta.sala, "Falta": alerta.tipo_falta, "Ruta": path}
        with csv_lock: pd.DataFrame([reg]).to_csv(DB_PATH, mode='a', header=not os.path.exists(DB_PATH), index=False)
    bt.add_task(process)
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)

