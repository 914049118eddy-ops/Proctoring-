// ==========================================
// MOTOR IA + PRISIÓN DIGITAL (FIEE UNI)
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;

// Persistencia para evitar falsos positivos
let contCelular = 0;
let contMirada = 0;
const UMBRAL_CELULAR = 2; // ~0.6s
const UMBRAL_MIRADA = 15; // ~0.5s

// --- 1. SEGURIDAD DEL NAVEGADOR (LOCKDOWN) ---

// Detectar si cambia de pestaña o ventana (Alt-Tab)
window.addEventListener('blur', () => {
    enviarAlertaServidor("CAMBIO DE PESTAÑA/VENTANA (Posible fraude)");
});

// Bloquear Clic Derecho (Inspeccionar)
document.addEventListener('contextmenu', e => e.preventDefault());

// Bloquear Copiar y Pegar
document.addEventListener('copy', e => e.preventDefault());
document.addEventListener('paste', e => e.preventDefault());

// Forzar Pantalla Completa
function activarFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(e => console.log("Click requerido"));
    }
}

// --- 2. COMUNICACIÓN Y UI ---

function agregarEventoVisual(texto) {
    const lista = document.getElementById('lista-eventos');
    const item = document.createElement('div');
    item.className = 'log-item';
    item.innerHTML = `<span style="color:#ef4444">⚠️ ${texto}</span> <span>${new Date().toLocaleTimeString()}</span>`;
    lista.prepend(item);
    
    const badge = document.getElementById('estado');
    badge.className = 'status-badge status-alert';
    badge.innerHTML = `🔴 Alerta: ${texto}`;
    setTimeout(() => {
        badge.className = 'status-badge status-ok';
        badge.innerHTML = '🟢 Monitoreo Activo';
    }, 3000);
}

async function enviarAlertaServidor(tipo) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    agregarEventoVisual(tipo);
    
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.5);

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img})
        });
    } catch (e) { console.error(e); }
    setTimeout(() => { enviandoAlerta = false; }, 5000);
}

// --- 3. MOTORES DE IA ---

// MediaPipe (Mirada)
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5});
faceMesh.onResults((res) => {
    if (res.multiFaceLandmarks?.length > 0) {
        const dX = Math.abs(res.multiFaceLandmarks[0][468].x - res.multiFaceLandmarks[0][33].x);
        if (dX < 0.012) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) { enviarAlertaServidor("Mirada Desviada"); contMirada = 0; }
        } else { contMirada = 0; }
    }
});

// YOLOv8 (Objetos)
async function initYOLO() {
    yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
}

async function inferenciaYOLO() {
    if (!yoloSession || enviandoAlerta) return;
    ctx.drawImage(video, 0, 0, 640, 640);
    const data = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = data[i*4]/255; input[640*640+i] = data[i*4+1]/255; input[2*640*640+i] = data[i*4+2]/255;
    }
    const output = await yoloSession.run({images: new ort.Tensor('float32', input, [1, 3, 640, 640])});
    const prob = output.output0.data;
    let detectado = false;
    for (let i = 0; i < 8400; i++) {
        if (prob[8400 * 71 + i] > 0.45) { detectado = true; break; }
    }
    if (detectado) {
        contCelular++;
        if (contCelular >= UMBRAL_CELULAR) { enviarAlertaServidor("Celular Detectado"); contCelular = 0; }
    } else { contCelular = 0; }
}

const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        if (Math.random() > 0.8) await inferenciaYOLO();
    },
    width: 640, height: 480
});

initYOLO().then(() => camera.start());
