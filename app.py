import os, base64, threading, uvicorn, pandas as pd, json, hashlib, uuid
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from typing import List, Dict, Tuple, Any

# ==========================================
# 🔐 FUNCION HASH
# ==========================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# ==========================================
# 1. CAPA DE DATOS
# ==========================================
class RepositorioDatosFIEE:
    def __init__(self):
        self.lock = threading.Lock()
        self.archivos = {
            "db": "database.csv",
            "asistencia": "asistencia.csv",
            "respuestas": "respuestas.csv",
            "salas": "salas.csv"
        }
        self.columnas = {
            "db": ["Fecha", "ID", "Nombre", "Sala", "Falta", "Ruta"],
            "asistencia": ["ID", "Nombre", "Sala", "Estado", "Camara", "Inicio"],
            "respuestas": ["ID", "Respuestas", "Fecha"],
            "salas": ["Sala", "Creado", "Docente"]
        }
        self._inicializar()

    def _inicializar(self):
        for d in ["evidencias", "static/js"]:
            os.makedirs(d, exist_ok=True)

        for k, r in self.archivos.items():
            if not os.path.exists(r) or os.stat(r).st_size == 0:
                pd.DataFrame(columns=self.columnas[k]).to_csv(r, index=False)

    def guardar(self, clave, registro):
        with self.lock:
            pd.DataFrame([registro]).to_csv(self.archivos[clave], mode='a', header=False, index=False)

    def actualizar(self, clave, uid, columna, valor):
        with self.lock:
            df = pd.read_csv(self.archivos[clave])
            df.loc[df['ID'] == uid, columna] = valor
            df.to_csv(self.archivos[clave], index=False)

    def obtener(self, clave):
        if not os.path.exists(self.archivos[clave]): return []
        return pd.read_csv(self.archivos[clave]).to_dict(orient="records")

    def limpiar(self, clave):
        with self.lock:
            pd.DataFrame(columns=self.columnas[clave]).to_csv(self.archivos[clave], index=False)

# ==========================================
# 2. CAPA LMS
# ==========================================
class GestorAcademicoLMS:
    def __init__(self, repo):
        self.repo = repo
        self.config_file = "examen_config.json"

    def registrar_sala(self, sala, docente, password):
        registro = {
            "Sala": sala.upper(),
            "Creado": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "Docente": docente
        }
        self.repo.guardar("salas", registro)

        docentes = {}
        if os.path.exists("docentes.json"):
            with open("docentes.json", "r") as f:
                docentes = json.load(f)

        docentes[docente] = {
            "password": hash_password(password),
            "sala": sala.upper()
        }

        with open("docentes.json", "w") as f:
            json.dump(docentes, f)

    def verificar_sala(self, sala):
        salas = self.repo.obtener("salas")
        return any(s["Sala"] == sala.upper() for s in salas)

    def matricular(self, uid, nombre, sala):
        self.repo.guardar("asistencia", {
            "ID": uid,
            "Nombre": nombre,
            "Sala": sala.upper(),
            "Estado": "EN EXAMEN",
            "Camara": "OK",
            "Inicio": datetime.now().strftime("%H:%M:%S")
        })

    def finalizar(self, uid, respuestas):
        self.repo.guardar("respuestas", {
            "ID": uid,
            "Respuestas": respuestas,
            "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self.repo.actualizar("asistencia", uid, "Estado", "FINALIZADO")

# ==========================================
# 3. CAPA IA
# ==========================================
class AnalizadorProctoring:
    def __init__(self, repo):
        self.repo = repo

    def registrar_alerta(self, uid, nombre, sala, falta, img_b64, camara_ok):
        timestamp = datetime.now().strftime("%H%M%S")
        ruta = f"evidencias/{uid}_{timestamp}.jpg"

        try:
            with open(ruta, "wb") as f:
                f.write(base64.b64decode(img_b64.split(",")[1]))
        except:
            pass

        if not camara_ok:
            self.repo.actualizar("asistencia", uid, "Camara", "BLOQUEADA")

        self.repo.guardar("db", {
            "Fecha": datetime.now().strftime("%H:%M:%S"),
            "ID": uid,
            "Nombre": nombre,
            "Sala": sala,
            "Falta": falta,
            "Ruta": ruta
        })

# ==========================================
# 🚀 INICIALIZACION
# ==========================================
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="proctor_2026_secure")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/ver_evidencia", StaticFiles(directory="evidencias"), name="evidencias")

repo = RepositorioDatosFIEE()
lms = GestorAcademicoLMS(repo)
ia = AnalizadorProctoring(repo)

# ==========================================
# 🏠 HOME
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <h1>Sistema Proctoring FIEE</h1>

    <h3>Crear Sala (Docente)</h3>
    <form action="/crear_sala" method="post">
    Docente: <input name="docente"><br>
    Sala: <input name="nombre_sala"><br>
    Password: <input type="password" name="password"><br>
    <button type="submit">Crear</button>
    </form>

    <hr>

    <h3>Login Docente</h3>
    <form action="/login_docente" method="post">
    Docente: <input name="docente"><br>
    Password: <input type="password" name="password"><br>
    <button type="submit">Ingresar</button>
    </form>

    <hr>

    <h3>Alumno</h3>
    <form action="/ingresar_alumno" method="post">
    Nombre: <input name="nombre"><br>
    UID: <input name="uid"><br>
    Sala: <input name="sala"><br>
    <button type="submit">Entrar</button>
    </form>
    """

# ==========================================
# 👨‍🏫 CREAR SALA
# ==========================================
@app.post("/crear_sala")
async def crear_sala(request: Request, docente: str = Form(...), nombre_sala: str = Form(...), password: str = Form(...)):
    lms.registrar_sala(nombre_sala, docente, password)
    request.session["docente"] = docente
    request.session["sala"] = nombre_sala.upper()

    link = f"http://localhost:8000/?sala={nombre_sala.upper()}"

    return HTMLResponse(f"""
    <h2>✅ Sala creada</h2>
    Código: {nombre_sala.upper()}<br>
    Link alumnos:<br>{link}<br><br>
    <a href="/dashboard">Ir al Dashboard</a><br>
    <a href="/">⬅ Volver</a>
    """)

# ==========================================
# 🔐 LOGIN DOCENTE
# ==========================================
@app.post("/login_docente")
async def login_docente(request: Request, docente: str = Form(...), password: str = Form(...)):
    if not os.path.exists("docentes.json"):
        return HTMLResponse("No existen docentes registrados")

    with open("docentes.json", "r") as f:
        docentes = json.load(f)

    if docente not in docentes:
        return HTMLResponse("Docente no registrado")

    if docentes[docente]["password"] != hash_password(password):
        return HTMLResponse("Password incorrecta")

    request.session["docente"] = docente
    request.session["sala"] = docentes[docente]["sala"]

    return RedirectResponse("/dashboard", status_code=303)

# ==========================================
# 🎓 INGRESO ALUMNO
# ==========================================
@app.post("/ingresar_alumno")
async def ingresar_alumno(nombre: str = Form(...), uid: str = Form(...), sala: str = Form(...)):
    if not lms.verificar_sala(sala):
        return HTMLResponse("Sala no encontrada")

    lms.matricular(uid, nombre, sala)
    return HTMLResponse(f"Alumno {nombre} ingresó correctamente")

# ==========================================
# 📊 DASHBOARD
# ==========================================
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if "docente" not in request.session:
        return RedirectResponse("/")

    docente = request.session["docente"]
    sala = request.session["sala"]

    asistencia = [a for a in repo.obtener("asistencia") if a["Sala"] == sala]
    incidencias = [i for i in repo.obtener("db") if i["Sala"] == sala]

    return f"""
    <h2>Dashboard - {docente}</h2>
    Sala: {sala}<br>
    Alumnos: {len(asistencia)}<br>
    Alertas: {len(incidencias)}<br><br>

    <form action="/cambiar_password" method="post">
    Nueva Password: <input type="password" name="nueva_password">
    <button type="submit">Cambiar</button>
    </form>

    <br>
    <a href="/logout">Cerrar Sesión</a><br>
    <a href="/">⬅ Volver</a>
    """

# ==========================================
# 🔑 CAMBIAR PASSWORD
# ==========================================
@app.post("/cambiar_password")
async def cambiar_password(request: Request, nueva_password: str = Form(...)):
    docente = request.session.get("docente")

    with open("docentes.json", "r") as f:
        docentes = json.load(f)

    docentes[docente]["password"] = hash_password(nueva_password)

    with open("docentes.json", "w") as f:
        json.dump(docentes, f)

    return HTMLResponse("Password actualizada <a href='/dashboard'>Volver</a>")

# ==========================================
# 🚪 LOGOUT
# ==========================================
@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

# ==========================================
# 🤖 API IA
# ==========================================
class ModeloTensorIA(BaseModel):
    uid: str
    nombre: str
    sala: str
    tipo_falta: str
    imagen_b64: str
    camara_ok: bool

@app.post("/api/alerta_ia")
async def alerta_ia(alerta: ModeloTensorIA, bt: BackgroundTasks):
    bt.add_task(ia.registrar_alerta, alerta.uid, alerta.nombre, alerta.sala, alerta.tipo_falta, alerta.imagen_b64, alerta.camara_ok)
    return {"estado": "ok"}

# ==========================================
# 🚀 RUN
# ==========================================
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)

