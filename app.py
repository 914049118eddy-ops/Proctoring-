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
ASISTENCIA_PATH = "asistencia.csv"
CLAVE_DOCENTE = "uni2026"
os.makedirs("evidencias", exist_ok=True)
csv_lock = threading.Lock()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

class Alerta(BaseModel):
    uid: str; nombre: str; materia: str; tipo_falta: str; imagen_b64: str

@app.get("/", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/ingresar")
async def ingresar(role: str = Form(...), nombre: str = Form(None), uid: str = Form(None), materia: str = Form(None), password: str = Form(None)):
    if role == "docente":
        if password == CLAVE_DOCENTE:
            return RedirectResponse(url=f"/dashboard?password={password}", status_code=303)
        return HTMLResponse("<h1>❌ Clave incorrecta</h1>", status_code=403)
    
    # --- REGISTRO DE ASISTENCIA ---
    registro_asist = {
        "Fecha_Ingreso": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ID": uid, "Nombre": nombre, "Materia": materia, "Estado": "En Examen"
    }
    with csv_lock:
        pd.DataFrame([registro_asist]).to_csv(ASISTENCIA_PATH, mode='a', header=not os.path.exists(ASISTENCIA_PATH), index=False)
    
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&materia={materia}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen(request: Request, uid: str, nombre: str, materia: str):
    return templates.TemplateResponse("cliente.html", {"request": request, "uid": uid, "nombre": nombre, "materia": materia})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE: return RedirectResponse(url="/")
    
    # Leer incidencias
    incidencias = pd.read_csv(DB_PATH).to_dict(orient="records") if os.path.exists(DB_PATH) else []
    # Leer asistencia
    asistencia = pd.read_csv(ASISTENCIA_PATH).to_dict(orient="records") if os.path.exists(ASISTENCIA_PATH) else []
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "incidencias": incidencias[::-1], 
        "asistencia": asistencia[::-1]
    })

@app.post("/api/alerta")
async def api_alerta(alerta: Alerta, bt: BackgroundTasks):
    def save():
        ts = datetime.now().strftime("%H%M%S")
        path = f"evidencias/{alerta.uid}_{ts}.jpg"
        with open(path, "wb") as f: f.write(base64.b64decode(alerta.imagen_b64.split(",")[1]))
        reg = {"Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "ID": alerta.uid, "Nombre": alerta.nombre, "Materia": alerta.materia, "Falta": alerta.tipo_falta, "Ruta": path}
        with csv_lock: pd.DataFrame([reg]).to_csv(DB_PATH, mode='a', header=not os.path.exists(DB_PATH), index=False)
    bt.add_task(save)
    return {"status": "ok"}

@app.get("/descargar_reporte")
async def reporte(password: str = None):
    if password == CLAVE_DOCENTE and os.path.exists(DB_PATH): return FileResponse(DB_PATH, filename="Reporte_Final.csv")
    raise HTTPException(status_code=404)

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
