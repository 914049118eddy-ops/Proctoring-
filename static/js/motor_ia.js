// ==========================================
// MOTOR IA V4.0 - FIEE UNI
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

// CONFIGURACIÓN DE PERSISTENCIA
let contMirada = 0;
const UMBRAL_MIRADA = 10; 
const SENSIBILIDAD_IRIS = 0.009; 

let contCelular = 0;
const UMBRAL_CELULAR = 3;

// --- DETECCIÓN DE CÁMARA TAPADA ---
async function detectarCamaraTapada() {
    ctx.drawImage(video, 0, 0, 10, 10); 
    const data = ctx.getImageData(0, 0, 10, 10).data;
    let brilloTotal = 0;
    for (let i = 0; i < data.length; i += 4) {
        brilloTotal += (data[i] + data[i+1] + data[i+2]) / 3;
    }
    const brilloPromedio = brilloTotal / 100;
    return brilloPromedio < 15; 
}

// --- SISTEMA DE COMUNICACIÓN ---
function agregarEventoVisual(texto) {
    const lista = document.getElementById('lista-eventos');
    const item = document.createElement('div');
    item.style.padding = "5px";
    item.style.borderBottom = "1px solid #eee";
    item.innerHTML = `<span style="color:#ef4444; font-weight:bold;">⚠️ ${texto}</span> <span style="color:#666; float:right;">${new Date().toLocaleTimeString()}</span>`;
    lista.prepend(item);
    
    const badge = document.getElementById('estado');
    badge.className = 'status-badge status-alert';
    badge.innerHTML = `🔴 Infracción: ${texto}`;
    
    setTimeout(() => {
        badge.className = 'status-badge status-ok';
        badge.innerHTML = '🟢 Monitoreo Activo';
    }, 4000);
}

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    
    agregarEventoVisual(tipo);
    
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.5);

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk})
        });
    } catch (e) { console.error("Error contactando servidor:", e); }
    
    setTimeout(() => enviandoAlerta = false, 5000);
}

// --- MEDIAPIPE (ROSTRO Y MIRADA) ---
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.7}); 

faceMesh.onResults(async (res) => {
    if (await detectarCamaraTapada()) {
        enviarAlerta("CÁMARA TAPADA/OSCURA", false);
        return;
    }

    if (res.multiFaceLandmarks?.length > 0) {
        const iris = res.multiFaceLandmarks[0];
        const dX = Math.abs(iris[468].x - iris[33].x);
        
        if (dX < SENSIBILIDAD_IRIS) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) {
                enviarAlerta("Desviación de Mirada");
                contMirada = 0;
            }
        } else { contMirada = 0; }
    }
});

// --- YOLOv8 (CELULARES) ---
async function initYOLO() {
    try {
        ort.env.wasm.numThreads = 2;
        yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
        console.log("✅ Modelo YOLO ONNX Cargado");
    } catch (e) { console.error("Error cargando YOLO:", e); }
}

async function inferirYOLO() {
    if (!yoloSession || enviandoAlerta) return;
    
    ctx.drawImage(video, 0, 0, 640, 640);
    const data = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = data[i*4]/255;
        input[640*640+i] = data[i*4+1]/255;
        input[2*640*640+i] = data[i*4+2]/255;
    }
    
    try {
        const tensor = new ort.Tensor('float32', input, [1, 3, 640, 640]);
        const output = await yoloSession.run({images: tensor});
        const prob = output.output0.data;
        
        let celular_detectado = false;
        for (let i = 0; i < 8400; i++) {
            if (prob[8400 * 71 + i] > 0.45) { // Clase 67 (Celular)
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

// --- ARRANQUE SEPARADO (SOLUCIÓN A CÁMARA NEGRA) ---
const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        frameCounter++;
        if (frameCounter % 8 === 0) await inferirYOLO(); // YOLO corre cada ~0.25s
    },
    width: 640, height: 480
});

// Arrancamos la cámara inmediatamente
camera.start().then(() => {
    document.getElementById('estado').innerHTML = "🟢 Cámara Iniciada";
    // Cargamos YOLO en segundo plano para no bloquear
    initYOLO();
}).catch(e => alert("Permite el acceso a la cámara."));
