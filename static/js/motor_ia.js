// ==========================================
// MOTOR IA V5.2 - FIEE UNI (ALTA SENSIBILIDAD)
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

// --- 1. PRISIÓN DIGITAL (SEGURIDAD DEL NAVEGADOR) ---
window.addEventListener('blur', () => {
    enviarAlerta("CAMBIO DE PESTAÑA/VENTANA (Posible búsqueda)", true);
});
document.addEventListener('contextmenu', e => e.preventDefault());
document.addEventListener('copy', e => e.preventDefault());
document.addEventListener('paste', e => e.preventDefault());

// --- 2. CALIBRACIÓN MATEMÁTICA (AJUSTADO) ---
// Mirada
let contMirada = 0;
const UMBRAL_MIRADA = 8; // Bajamos a ~0.25 segundos para que sea rápido
const SENSIBILIDAD_IRIS = 0.015; // Aumentamos el valor: ahora detecta desvíos más sutiles

// Objetos (YOLO)
let contCelular = 0;
const UMBRAL_CELULAR = 2; // Con solo verlo 2 veces seguidas, dispara
const CONFIANZA_YOLO = 0.32; // Bajamos de 0.45 a 0.32. Las webcams suelen tener ruido, esto maximiza el Recall.

// --- 3. DETECCIÓN DE CÁMARA TAPADA ---
async function detectarCamaraTapada() {
    ctx.drawImage(video, 0, 0, 10, 10); 
    const data = ctx.getImageData(0, 0, 10, 10).data;
    let brilloTotal = 0;
    for (let i = 0; i < data.length; i += 4) {
        brilloTotal += (data[i] + data[i+1] + data[i+2]) / 3;
    }
    return (brilloTotal / 100) < 15; 
}

// --- 4. SISTEMA DE COMUNICACIÓN CON PYTHON ---
function agregarEventoVisual(texto) {
    const lista = document.getElementById('lista-eventos');
    if(lista) {
        const item = document.createElement('div');
        item.style.padding = "5px";
        item.style.borderBottom = "1px solid #eee";
        item.innerHTML = `<span style="color:#ef4444; font-weight:bold;">⚠️ ${texto}</span> <span style="color:#666; float:right;">${new Date().toLocaleTimeString()}</span>`;
        lista.prepend(item);
    }
    
    const badge = document.getElementById('estado');
    if(badge) {
        badge.className = 'status-badge status-alert';
        badge.innerHTML = `🔴 Infracción: ${texto}`;
        setTimeout(() => {
            badge.className = 'status-badge status-ok';
            badge.innerHTML = '🟢 Monitoreo Activo';
        }, 4000);
    }
}

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    
    agregarEventoVisual(tipo);
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.6); // Subimos un poco la calidad de la evidencia

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk})
        });
    } catch (e) { console.error("Error contactando servidor:", e); }
    
    setTimeout(() => enviandoAlerta = false, 4000); // Reducimos el cooldown para atrapar trampas seguidas
}

// --- 5. MODELOS DE IA ---

// MediaPipe (Rostro)
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
// Bajamos minDetectionConfidence a 0.5 para que no pierda el rostro si el alumno se mueve rápido
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5}); 

faceMesh.onResults(async (res) => {
    if (await detectarCamaraTapada()) {
        enviarAlerta("CÁMARA TAPADA/OSCURA", false);
        return;
    }
    if (res.multiFaceLandmarks && res.multiFaceLandmarks.length > 0) {
        const iris = res.multiFaceLandmarks[0];
        // Cálculo de geometría facial
        const dX = Math.abs(iris[468].x - iris[33].x);
        
        // Descomenta la siguiente línea y abre (F12) si quieres ver los números exactos de tu ojo
        // console.log("Distancia Iris:", dX); 

        if (dX < SENSIBILIDAD_IRIS) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) {
                enviarAlerta("Desviación de Mirada Detectada");
                contMirada = 0;
            }
        } else { contMirada = 0; }
    }
});

// YOLOv8 (Objetos)
async function inferirYOLO() {
    if (!yoloSession || enviandoAlerta) return;
    ctx.drawImage(video, 0, 0, 640, 640);
    const data = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = data[i*4]/255.0;
        input[640*640+i] = data[i*4+1]/255.0;
        input[2*640*640+i] = data[i*4+2]/255.0;
    }
    try {
        const tensor = new ort.Tensor('float32', input, [1, 3, 640, 640]);
        const output = await yoloSession.run({images: tensor});
        const prob = output.output0.data;
        
        let celular_detectado = false;
        // Exploración de tensores: La clase 67 es el celular. 4 coordenadas de caja + 67 = 71
        for (let i = 0; i < 8400; i++) {
            if (prob[71 * 8400 + i] > CONFIANZA_YOLO) { 
                celular_detectado = true; 
                break; 
            }
        }
        
        if(celular_detectado) {
            contCelular++;
            if(contCelular >= UMBRAL_CELULAR) { 
                enviarAlerta("Teléfono Celular Detectado"); 
                contCelular = 0; 
            }
        } else { contCelular = 0; }
    } catch(e) { console.error("Error en inferencia:", e); }
}

// --- 6. ARRANQUE DESACOPLADO (Cámara Siempre Enciende) ---
const camera = new Camera(video, {
    onFrame: async () => {
        try {
            await faceMesh.send({image: video});
            frameCounter++;
            // Aumentamos la frecuencia de YOLO: ahora evalúa cada ~0.15s
            if (frameCounter % 5 === 0) await inferirYOLO(); 
        } catch(e) {}
    },
    width: 640, height: 480
});

camera.start().then(() => {
    const badge = document.getElementById('estado');
    if(badge) badge.innerHTML = "⏳ Cámara OK. Cargando IA...";
    
    setTimeout(async () => {
        try {
            yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
            console.log("✅ Motor YOLO ONNX Cargado y Listo");
            if(badge) badge.innerHTML = "🟢 Monitoreo Activo";
        } catch(e) {
            console.error("Error cargando IA de objetos:", e);
        }
    }, 500);
}).catch(e => {
    alert("Error crítico: Permite el acceso a la cámara.");
});
