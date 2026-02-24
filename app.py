import os, base64, threading, uvicorn
from datetime import datetime
import pandas as pd
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Proctoring UNI - FIEE")
templates = Jinja2Templates(directory="templates")

# Configuración de Rutas y Seguridad
CLAVE_DOCENTE = "uni2026"
DB_PATH = "database.csv"
os.makedirs("evidencias", exist_ok=True)
csv_lock = threading.Lock()

# Montajes Estáticos (Crucial)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")
# Para que el JS encuentre el modelo en la raíz
app.mount("/model", StaticFiles(directory="."), name="model")

class AlertaProctoring(BaseModel):
    uid: str
    nombre: str
    materia: str
    tipo_falta: str
    imagen_b64: str

def guardar_datos(alerta: AlertaProctoring):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_img = f"evidencias/{alerta.uid}_{timestamp}.jpg"
    try:
        b64_data = alerta.imagen_b64.split(",")[1] if "," in alerta.imagen_b64 else alerta.imagen_b64
        with open(ruta_img, "wb") as f:
            f.write(base64.b64decode(b64_data))
    except: ruta_img = "error_img"

    registro = {
        "Fecha_Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ID_Estudiante": alerta.uid,
        "Nombre": alerta.nombre,
        "Materia": alerta.materia,
        "Falta_Detectada": alerta.tipo_falta,
        "Ruta_Evidencia": ruta_img
    }
    with csv_lock:
        pd.DataFrame([registro]).to_csv(DB_PATH, mode='a', header=not os.path.exists(DB_PATH), index=False)

@app.get("/", response_class=HTMLResponse)
async def login(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/ingresar")
async def ingresar(uid: str = Form(...), nombre: str = Form(...), materia: str = Form(...)):
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&materia={materia}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen(request: Request, uid: str, nombre: str, materia: str):
    return templates.TemplateResponse("cliente.html", {"request": request, "uid": uid, "nombre": nombre, "materia": materia})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE:
        return HTMLResponse("<h1>🚫 Acceso Denegado</h1>", status_code=403)
    incidencias = pd.read_csv(DB_PATH).to_dict(orient="records") if os.path.exists(DB_PATH) else []
    return templates.TemplateResponse("dashboard.html", {"request": request, "incidencias": incidencias[::-1]})

@app.post("/api/alerta")
async def api_alerta(alerta: AlertaProctoring, tasks: BackgroundTasks):
    tasks.add_task(guardar_datos, alerta)
    return {"status": "ok"}

@app.get("/descargar_reporte")
async def reporte(password: str = None):
    if password == CLAVE_DOCENTE and os.path.exists(DB_PATH):
        return FileResponse(DB_PATH, filename="Reporte_FIEE.csv")
    raise HTTPException(403)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)



