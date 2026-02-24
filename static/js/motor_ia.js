const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

// --- VARIABLES DE PERSISTENCIA (ANTI-FALSAS ALARMAS) ---
let enviandoAlerta = false;
let yoloSession = null;

let contadorCelular = 0;
const FRAMES_REQUERIDOS_CELULAR = 2; // ~0.6s (ya que YOLO corre cada 10 frames)

let contadorMirada = 0;
const FRAMES_REQUERIDOS_MIRADA = 15; // ~0.5s (MediaPipe corre a ~30fps)

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
        badge.innerHTML = '🟢 Monitoreo Estable';
    }, 3000);
}

async function enviarAlertaServidor(tipo) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    
    agregarEventoVisual(tipo);
    
    ctx.drawImage(video, 0, 0, 640, 480);
    const imgBase64 = canvas.toDataURL('image/jpeg', 0.5);

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: imgBase64})
        });
    } catch (e) { console.error("Error de red:", e); }
    
    setTimeout(() => { enviandoAlerta = false; }, 5000);
}

// --- MEDIAPIPE CON PERSISTENCIA ---
const faceMesh = new FaceMesh({
    locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${file}`
});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5});

faceMesh.onResults((results) => {
    if (results.multiFaceLandmarks?.length > 0) {
        const landmarks = results.multiFaceLandmarks[0];
        const dX = Math.abs(landmarks[468].x - landmarks[33].x);
        
        if (dX < 0.012) {
            contadorMirada++;
            if (contadorMirada > FRAMES_REQUERIDOS_MIRADA) {
                enviarAlertaServidor("Mirada Desviada Prolongada");
                contadorMirada = 0;
            }
        } else {
            contadorMirada = 0; // Reset si vuelve a mirar al centro
        }
    }
});

// --- YOLOv8 CON PERSISTENCIA ---
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
    
    let celularEncontrado = false;
    for (let i = 0; i < 8400; i++) {
        if (data[8400 * 71 + i] > 0.45) { // Bajamos un poco el umbral pero pedimos persistencia
            celularEncontrado = true;
            break;
        }
    }

    if (celularEncontrado) {
        contadorCelular++;
        if (contadorCelular >= FRAMES_REQUERIDOS_CELULAR) {
            enviarAlertaServidor("Uso de Celular Confirmado");
            contadorCelular = 0;
        }
    } else {
        contadorCelular = 0; // Si desaparece el celular un solo frame, reiniciamos cuenta
    }
}

const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        frameCounter++;
        if (frameCounter % 10 === 0) await inferenciaYOLO();
    },
    width: 640, height: 480
});
let frameCounter = 0;

initYOLO().then(() => camera.start());
