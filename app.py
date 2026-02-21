import streamlit as st
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, RTCConfiguration
from streamlit_autorefresh import st_autorefresh
import cv2
import pandas as pd
import numpy as np
import mediapipe as mp
from ultralytics import YOLO
from datetime import datetime
import time
import os   
import av
import threading
import atexit
import glob
from abc import ABC, abstractmethod

# --- CONFIGURACIÓN ---
RTC_CONFIGURATION = RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]})
ARCHIVO_RESUMEN_TOTAL = "resumen_final_examen.csv"
ARCHIVO_ASISTENCIA_INMEDIATA = "asistencia_general.csv"

# ==========================================
# 1. CLASES DE DATOS (POO)
# ==========================================
class Persona(ABC):
    def __init__(self, id_str, nombre):
        self._id = id_str
        self._nombre = nombre
        self._fecha_registro = datetime.now()

    @abstractmethod
    def obtener_info(self):
        pass

class Estudiante(Persona):
    def __init__(self, id_str, nombre, carrera, materia, tipo_examen):
        super().__init__(id_str, nombre)
        self.carrera = carrera
        self.materia = materia
        self.tipo_examen = tipo_examen
        self.puntos_sospecha = 0.0
        self.asistencia_firmada = False 

    def obtener_info(self):
        return {
            "ID": self._id, "Nombre": self._nombre,
            "Carrera": self.carrera, "Materia": self.materia,
            "Examen": self.tipo_examen, "Riesgo": round(self.puntos_sospecha, 2)
        }

# ==========================================
# 2. LÓGICA DE ANÁLISIS (IA)
# ==========================================
class Analizador(ABC):
    def __init__(self):
        # Modelos Nano para máxima fluidez
        self.model = YOLO('yolov8n.pt')
        self.pose = mp.solutions.pose.Pose(model_complexity=0, min_detection_confidence=0.5)
        self.face = mp.solutions.face_mesh.FaceMesh(refine_landmarks=True, min_detection_confidence=0.5)
        self.contador_frames = 0
        self._lock = threading.Lock() #here

    @abstractmethod
    def analizar(self, frame):
        pass

class AnalizadorDetallado(Analizador):
    def __init__(self, estudiante):
        super().__init__()
        self.estudiante = estudiante
        self.ultima_incidencia = 0.0

    def __registrar_asistencia_inmediata(self):
        """Registro crítico: se ejecuta al detectar el primer frame del alumno"""
        with self._lock:
            if not self.estudiante.asistencia_firmada:
                datos = {
                    'Fecha': datetime.now().strftime("%Y-%m-%d"),
                    'Hora': datetime.now().strftime("%H:%M:%S"),
                    'ID': self.estudiante._id,
                    'Nombre': self.estudiante._nombre,
                    'Materia': self.estudiante.materia,
                    'Estado': 'PRESENTE'
                }
                pd.DataFrame([datos]).to_csv(ARCHIVO_ASISTENCIA_INMEDIATA, mode='a', 
                    header=not os.path.exists(ARCHIVO_ASISTENCIA_INMEDIATA), index=False)
                self.estudiante.asistencia_firmada = True #here

    def __clasificar_riesgo(self, tipo, peso):
        tiempo_actual = time.time()
        if tiempo_actual - self.ultima_incidencia > 1.5:
            with self._lock:
                self.estudiante.puntos_sospecha += peso
                log = self.estudiante.obtener_info()
                log['Hora'] = datetime.now().strftime("%H:%M:%S")
                log['Evento'] = tipo
                log['Pts_Evento'] = peso
                
                nombre_archivo = f"{self.estudiante._id}.csv"
                pd.DataFrame([log]).to_csv(nombre_archivo, mode='a',
                    header=not os.path.exists(nombre_archivo), index=False)
                self.ultima_incidencia = tiempo_actual

    def analizar(self, frame):
        # Prioridad: Registrar asistencia si no está firmada
        if not self.estudiante.asistencia_firmada:
            self.__registrar_asistencia_inmediata()

        self.contador_frames += 1
        # Salto de frames para mantener fluidez (1 de cada 3)
        if self.contador_frames % 3 != 0: 
            return frame

        # Redimensionar para no saturar CPU
        img_small = cv2.resize(frame, (480, 270))
        rgb = cv2.cvtColor(img_small, cv2.COLOR_BGR2RGB)

        # 1. Análisis de Pose (Hombros)
        res_pose = self.pose.process(rgb)
        if res_pose.pose_landmarks:
            p = res_pose.pose_landmarks.landmark
            if abs(p[11].y - p[12].y) > 0.07: 
                self.__clasificar_riesgo("Inclinacion Hombros", 0.3)

        # 2. Análisis de Mirada (Iris)
        res_face = self.face.process(rgb)
        if res_face.multi_face_landmarks:
            m = res_face.multi_face_landmarks[0].landmark
            # Lógica Iris: detecta si la pupila se aleja del centro
            mira_lados = abs(m[468].x - m[33].x) < 0.012 or abs(m[468].x - m[133].x) < 0.012
            if mira_lados: 
                self.__clasificar_riesgo("Mirada Desviada", 0.3)

        # 3. Detección de Celular (YOLO)
        results = self.model.predict(img_small, conf=0.5, imgsz=320, verbose=False, classes=[67])
        if len(results[0].boxes) > 0: 
            self.__clasificar_riesgo("Celular Detectado", 1.5)

        return frame

# ==========================================
# 3. CONTROLADOR
# ==========================================
class Examen:
    def __init__(self, materia, estudiante):
        self._materia = materia
        self._estudiante = estudiante
        self._analizador = AnalizadorDetallado(estudiante)

    def ejecutar_analisis(self, frame):
        return self._analizador.analizar(frame)

class ProcesadorIA(VideoProcessorBase):
    def __init__(self):
        self.examen = None 

    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        if self.examen:
            try:
                img = self.examen.ejecutar_analisis(img)
            except Exception: 
                pass
        return av.VideoFrame.from_ndarray(img, format="bgr24")

# ==========================================
# 4. PORTAL WEB (STREAMLIT)
# ==========================================
class PortalExamen:
    def __init__(self):
        st.set_page_config(page_title="IA Proctoring UNI", layout="wide")
        if 'sesion_examen' in st.session_state:
            st_autorefresh(interval=1500, key="ui_refresh")
        
        if 'cierre_ok' not in st.session_state:
            atexit.register(self.consolidar_resumen_final)
            st.session_state.cierre_ok = True

    @staticmethod
    def consolidar_resumen_final():
        """Une todos los CSVs individuales al cerrar la app"""
        archivos = [f for f in glob.glob("*.csv") if f not in [ARCHIVO_RESUMEN_TOTAL, ARCHIVO_ASISTENCIA_INMEDIATA]]
        if archivos:
            lista_final = []
            for f in archivos:
                try:
                    df = pd.read_csv(f)
                    if not df.empty:
                        lista_final.append(df.iloc[[-1]])
                except: continue
            if lista_final:
                pd.concat(lista_final, ignore_index=True).to_csv(ARCHIVO_RESUMEN_TOTAL, index=False)

    def mostrar_interfaz(self):
        if 'sesion_examen' not in st.session_state:
            self._render_login()
        else:
            self._render_examen()

    def _render_login(self):
        st.title("🛡️ Sistema de Supervisión IA")
        with st.form("login"):
            c1, c2 = st.columns(2)
            with c1:
                n = st.text_input("Nombres y Apellidos")
                i = st.text_input("CÓDIGO")
            with c2:
                m = st.selectbox("Materia", ["POO", "BFI01", "BFI03"])
                t = st.selectbox("Tipo de Examen", ["PC1","PC2","PC3","PC4","Parcial", "Final"])
            
            if st.form_submit_button("Empezar Examen"):
                if n and i:
                    alumno = Estudiante(i, n, "Sistemas", m, t)
                    st.session_state.sesion_examen = Examen(m, alumno)
                    st.rerun()
                else:
                    st.error("Campos obligatorios")

    def _render_examen(self):
        ex = st.session_state.sesion_examen
        est = ex._estudiante
        
        st.header(f"📝 Examen de {ex._materia}")
        c1, c2 = st.columns([3, 1])
        
        with c2:
            st.subheader("Estado")
            if est.asistencia_firmada:
                st.success("✅ Asistencia Registrada")
            st.metric("Puntos de Sospecha", f"{est.puntos_sospecha:.2f}")
            
            if st.button("🔴 Finalizar y Enviar"):
                st.session_state.clear()
                st.rerun()

        with c1:
            ctx = webrtc_streamer(
                key=f"proctor-{est._id}",
                video_processor_factory=ProcesadorIA,
                rtc_configuration=RTC_CONFIGURATION,
                media_stream_constraints={"video": True, "audio": False},
                async_processing=True
            )
            # Inyección crítica para que el procesador tenga acceso al objeto Examen
            if ctx.video_processor:
                ctx.video_processor.examen = ex

if __name__ == "__main__":
    PortalExamen().mostrar_interfaz()