import os, base64, threading, uvicorn, pandas as pd
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="UNI Proctoring System")
templates = Jinja2Templates(directory="templates")

# Configuración de Rutas y Seguridad
DB_PATH = "database.csv"
CLAVE_DOCENTE = "uni2026"
os.makedirs("evidencias", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
csv_lock = threading.Lock()

# Montaje de archivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

class Alerta(BaseModel):
    uid: str
    nombre: str
    materia: str
    tipo_falta: str
    imagen_b64: str

def guardar_datos(alerta: Alerta):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_img = f"evidencias/{alerta.uid}_{ts}.jpg"
    try:
        # Decodificar y guardar imagen
        header, encoded = alerta.imagen_b64.split(",", 1)
        with open(ruta_img, "wb") as f:
            f.write(base64.b64decode(encoded))
        
        # Registrar en CSV
        registro = {
            "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ID": alerta.uid, 
            "Nombre": alerta.nombre,
            "Materia": alerta.materia, 
            "Falta": alerta.tipo_falta, 
            "Ruta": ruta_img
        }
        with csv_lock:
            df = pd.DataFrame([registro])
            df.to_csv(DB_PATH, mode='a', header=not os.path.exists(DB_PATH), index=False)
    except Exception as e:
        print(f"Error procesando alerta: {e}")

@app.get("/", response_class=HTMLResponse)
async def registro(request: Request):
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/ingresar")
async def ingresar(uid: str = Form(...), nombre: str = Form(...), materia: str = Form(...)):
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&materia={materia}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen(request: Request, uid: str, nombre: str, materia: str):
    return templates.TemplateResponse("cliente.html", {
        "request": request, "uid": uid, "nombre": nombre, "materia": materia
    })

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, password: str = None):
    if password != CLAVE_DOCENTE:
        return HTMLResponse("<h1>🚫 Acceso Denegado: Clave incorrecta</h1>", status_code=403)
    
    incidencias = []
    if os.path.exists(DB_PATH):
        df = pd.read_csv(DB_PATH)
        incidencias = df.to_dict(orient="records")
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "incidencias": incidencias[::-1]
    })

@app.get("/descargar_reporte")
async def reporte(password: str = None):
    if password == CLAVE_DOCENTE and os.path.exists(DB_PATH):
        return FileResponse(DB_PATH, filename="Reporte_FIEE_UNI.csv")
    raise HTTPException(status_code=404, detail="Archivo no encontrado")

@app.post("/api/alerta")
async def api_alerta(alerta: Alerta, bt: BackgroundTasks):
    bt.add_task(guardar_datos, alerta)
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
