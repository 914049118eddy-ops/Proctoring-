// ==========================================
// MOTOR IA V3.0 - FIEE UNI (CORREGIDO)
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

// --- FILTROS DE PERSISTENCIA (AJUSTE ACADÉMICO) ---
let contCelular = 0;
const UMBRAL_CELULAR = 3;  // Requiere ~1 segundo de presencia constante

let contMirada = 0;
const UMBRAL_MIRADA = 45; // Requiere ~1.5 segundos a 30fps

// --- SISTEMA DE COMUNICACIÓN ---
async function enviarAlertaServidor(tipo) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    
    // UI Feedback
    const badge = document.getElementById('estado');
    badge.className = 'status-badge status-alert';
    badge.innerHTML = `🔴 Alerta: ${tipo}`;
    
    const lista = document.getElementById('lista-eventos');
    const item = document.createElement('div');
    item.className = 'log-item';
    item.innerHTML = `<span style="color:#ef4444">⚠️ ${tipo}</span> <span>${new Date().toLocaleTimeString()}</span>`;
    lista.prepend(item);

    // Captura de evidencia
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.5);

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img})
        });
    } catch (e) { console.error("Error servidor:", e); }
    
    setTimeout(() => { 
        enviandoAlerta = false;
        badge.className = 'status-badge status-ok';
        badge.innerHTML = '🟢 Monitoreo Activo';
    }, 5000); 
}

// --- CONFIGURACIÓN DE PANTALLA COMPLETA ---
window.addEventListener('blur', () => enviarAlertaServidor("Cambio de Pestaña"));

// --- MEDIAPIPE (OJOS) ---
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5});

faceMesh.onResults((res) => {
    if (res.multiFaceLandmarks?.length > 0) {
        const iris = res.multiFaceLandmarks[0];
        const dX = Math.abs(iris[468].x - iris[33].x);
        
        if (dX < 0.012) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) {
                enviarAlertaServidor("Mirada Sospechosa");
                contMirada = 0;
            }
        } else { contMirada = 0; }
    }
});

// --- YOLO (CELULAR) ---
async function initYOLO() {
    try {
        yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
        console.log("IA YOLO Cargada");
    } catch (e) { console.error("Error YOLO:", e); }
}

async function inferir() {
    if (!yoloSession || enviandoAlerta) return;
    
    ctx.drawImage(video, 0, 0, 640, 640);
    const pixels = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = pixels[i*4]/255; 
        input[640*640+i] = pixels[i*4+1]/255; 
        input[2*640*640+i] = pixels[i*4+2]/255;
    }
    
    const output = await yoloSession.run({images: new ort.Tensor('float32', input, [1, 3, 640, 640])});
    const prob = output.output0.data;
    
    let celular = false;
    for (let i = 0; i < 8400; i++) {
        if (prob[8400 * 71 + i] > 0.45) { celular = true; break; }
    }

    if (celular) {
        contCelular++;
        if (contCelular >= UMBRAL_CELULAR) {
            enviarAlertaServidor("Objeto no permitido (Celular)");
            contCelular = 0;
        }
    } else { contCelular = 0; }
}

// --- ARRANQUE DE CÁMARA ---
const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        frameCounter++;
        if (frameCounter % 15 === 0) await inferir(); // YOLO cada 0.5s aprox
    },
    width: 640, height: 480
});

// Inicialización en cadena para asegurar que la cámara encienda
initYOLO().then(() => {
    camera.start().then(() => {
        console.log("Cámara Encendida");
        document.getElementById('estado').innerHTML = '🟢 Monitoreo Activo';
    }).catch(e => alert("Error al encender cámara. Revisa permisos."));
});
