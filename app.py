import os
import base64
import threading
from datetime import datetime
import pandas as pd
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

# ==========================================
# CONFIGURACIÓN INICIAL
# ==========================================
app = FastAPI(title="Proctoring UNI - Edge Architecture")
templates = Jinja2Templates(directory="templates")

from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
# ... (tus otros imports)

@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    """Página inicial de registro para el alumno."""
    return templates.TemplateResponse("registro.html", {"request": request})

@app.post("/ingresar")
async def ingresar_examen(uid: str = Form(...), nombre: str = Form(...), materia: str = Form(...)):
    """Recibe los datos y redirige al examen con los datos en la URL."""
    # Redirigimos al examen pasando los datos como parámetros
    return RedirectResponse(url=f"/examen?uid={uid}&nombre={nombre}&materia={materia}", status_code=303)

@app.get("/examen", response_class=HTMLResponse)
async def examen_page(request: Request, uid: str, nombre: str, materia: str):
    """Página del examen que recibe los datos del alumno."""
    return templates.TemplateResponse("cliente.html", {
        "request": request,
        "uid": uid,
        "nombre": nombre,
        "materia": materia
    })

@app.get("/descargar_reporte")
async def descargar_reporte(password: str = None):
    """Genera y descarga el CSV limpio para el profesor."""
    if password != CLAVE_DOCENTE:
        raise HTTPException(status_code=403, detail="No autorizado")
    
    # Aquí puedes llamar a tu lógica original de generar_reporte_limpio
    # Por ahora, simplemente enviamos el archivo generado
    if os.path.exists(DB_PATH):
        return FileResponse(path=DB_PATH, filename="Reporte_Proctoring_FIEE.csv", media_type='text/csv')
    raise HTTPException(status_code=404, detail="No hay datos registrados")

# Crear directorios y base de datos si no existen
os.makedirs("evidencias", exist_ok=True)
DB_PATH = "database.csv"
csv_lock = threading.Lock() # Evita errores si 2 alumnos hacen trampa al mismo tiempo

# Esto permite que el HTML encuentre el archivo /static/js/motor_ia.js
app.mount("/static", StaticFiles(directory="."), name="static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# ==========================================
# MODELO DE DATOS
# ==========================================
class AlertaProctoring(BaseModel):
    uid: str
    nombre: str
    materia: str
    tipo_falta: str
    imagen_b64: str  # La captura de pantalla en Base64

# ==========================================
# LÓGICA DE NEGOCIO (GUARDADO)
# ==========================================
def procesar_evidencia(alerta: AlertaProctoring):
    """Guarda la imagen y registra la alerta en el CSV en segundo plano."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. Guardar la imagen (Evidencia)
    ruta_img = f"evidencias/{alerta.uid}_{alerta.tipo_falta.replace(' ', '_')}_{timestamp}.jpg"
    try:
        # Limpiar el encabezado de base64 si existe
        if "," in alerta.imagen_b64:
            b64_data = alerta.imagen_b64.split(",")[1]
        else:
            b64_data = alerta.imagen_b64
            
        with open(ruta_img, "wb") as f:
            f.write(base64.b64decode(b64_data))
    except Exception as e:
        print(f"Error guardando imagen: {e}")
        ruta_img = "Error_Decodificacion"

    # 2. Registrar en Pandas (CSV)
    nuevo_registro = {
        "Fecha_Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ID_Estudiante": alerta.uid,
        "Nombre": alerta.nombre,
        "Materia": alerta.materia,
        "Falta_Detectada": alerta.tipo_falta,
        "Ruta_Evidencia": ruta_img
    }
    
    with csv_lock:
        df = pd.DataFrame([nuevo_registro])
        df.to_csv(DB_PATH, mode='a', header=not os.path.exists(DB_PATH), index=False)
        print(f"✅ Registrado: {alerta.uid} - {alerta.tipo_falta}")

# ==========================================
# ENDPOINTS
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def panel_examen(request: Request):
    """Entrega la página web al alumno (el motor de IA va incluido ahí)."""
    return templates.TemplateResponse("cliente.html", {"request": request})

# ... (Tus imports y configuración anterior)

# Definir una clave simple para el docente
CLAVE_DOCENTE = "uni2026"

@app.get("/dashboard", response_class=HTMLResponse)
async def ver_dashboard(request: Request, password: str = None):
    """
    Ruta protegida. Solo entra si la URL es: /dashboard?password=uni2026
    """
    if password != CLAVE_DOCENTE:
        return HTMLResponse(content="<h1>🚫 Acceso Denegado: Clave incorrecta</h1>", status_code=403)

    incidencias = []
    if os.path.exists(DB_PATH):
        df = pd.read_csv(DB_PATH)
        incidencias = df.to_dict(orient="records")
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "incidencias": incidencias[::-1]
    })

# Montamos la carpeta de evidencias para que las imágenes sean visibles en el navegador
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

@app.post("/api/alerta")
async def recibir_alerta(alerta: AlertaProctoring, background_tasks: BackgroundTasks):
    """Recibe la alerta del navegador y la procesa sin bloquear el servidor."""
    # Usamos BackgroundTasks para que el servidor responda instantáneamente
    background_tasks.add_task(procesar_evidencia, alerta)
    return {"status": "ok", "mensaje": "Alerta procesada exitosamente"}

if __name__ == "__main__":
    # Render usa la variable de entorno PORT
    port = int(os.environ.get("PORT", 8000))
    # Importante: host 0.0.0.0 para que sea accesible externamente
    uvicorn.run("app:app", host="0.0.0.0", port=port)





