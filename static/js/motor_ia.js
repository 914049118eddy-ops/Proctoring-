// ==========================================
// CONFIGURACIÓN DE IA DISTRIBUIDA
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });
let enviandoAlerta = false;
let yoloSession = null;

function agregarEventoVisual(texto) {
    const lista = document.getElementById('lista-eventos');
    const item = document.createElement('div');
    item.className = 'log-item';
    item.innerHTML = `<span style="color:#ef4444">⚠️ ${texto}</span> <span>${new Date().toLocaleTimeString()}</span>`;
    lista.prepend(item);
    
    const badge = document.getElementById('estado');
    badge.className = 'status-badge status-alert';
    badge.innerHTML = `🔴 Infracción: ${texto}`;
    
    setTimeout(() => {
        badge.className = 'status-badge status-ok';
        badge.innerHTML = '🟢 Monitoreo Activo';
    }, 3000);
}

async function enviarAlertaServidor(tipo) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    
    agregarEventoVisual(tipo);
    
    // Captura de evidencia
    ctx.drawImage(video, 0, 0, 640, 480);
    const imgBase64 = canvas.toDataURL('image/jpeg', 0.6);

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                uid: DATOS_ALUMNO.uid,
                nombre: DATOS_ALUMNO.nombre,
                materia: DATOS_ALUMNO.materia,
                tipo_falta: tipo,
                imagen_b64: imgBase64
            })
        });
    } catch (e) { console.error("Error de red:", e); }
    
    setTimeout(() => { enviandoAlerta = false; }, 5000);
}

// Configuración MediaPipe (FaceMesh)
const faceMesh = new FaceMesh({
    locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`
});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5});

faceMesh.onResults((results) => {
    if (results.multiFaceLandmarks?.length > 0) {
        const landmarks = results.multiFaceLandmarks[0];
        // Cálculo de desviación de iris
        const dX = Math.abs(landmarks[468].x - landmarks[33].x);
        if (dX < 0.012) enviarAlertaServidor("Mirada Desviada");
    }
});

// Configuración YOLOv8 (ONNX Runtime)
async function initYOLO() {
    try {
        yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
        console.log("YOLOv8 Online");
    } catch (e) { console.error("ONNX Error:", e); }
}

async function inferenciaYOLO() {
    if (!yoloSession || enviandoAlerta) return;
    
    ctx.drawImage(video, 0, 0, 640, 640);
    const pixels = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = pixels[i*4]/255.0;
        input[640*640+i] = pixels[i*4+1]/255.0;
        input[2*640*640+i] = pixels[i*4+2]/255.0;
    }
    
    const tensor = new ort.Tensor('float32', input, [1, 3, 640, 640]);
    const output = await yoloSession.run({images: tensor});
    const data = output.output0.data;
    
    for (let i = 0; i < 8400; i++) {
        if (data[8400 * 71 + i] > 0.55) { // Clase 67 (Cell Phone) + 4 coords
            enviarAlertaServidor("Celular Detectado");
            break;
        }
    }
}

// Bucle de Cámara
const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        if (Math.random() > 0.8) await inferenciaYOLO();
    },
    width: 640, height: 480
});

initYOLO().then(() => camera.start());
