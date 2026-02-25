// ==========================================
// MOTOR IA V7.0 - FIEE UNI (GAZE RATIO & HIGH RECALL)
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

// --- PRISIÓN DIGITAL ---
window.addEventListener('blur', () => enviarAlerta("Cambio de Pestaña (Posible Fraude)", true));
document.addEventListener('contextmenu', e => e.preventDefault());
document.addEventListener('copy', e => e.preventDefault());
document.addEventListener('paste', e => e.preventDefault());

function agregarEventoVisual(texto) {
    const lista = document.getElementById('lista-eventos');
    if(lista) {
        const item = document.createElement('div');
        item.style.padding = "5px";
        item.style.borderBottom = "1px solid #eee";
        item.innerHTML = `<span style="color:#ef4444; font-weight:bold;">⚠️ ${texto}</span>`;
        lista.prepend(item);
    }
    const badge = document.getElementById('estado');
    if(badge) {
        badge.className = 'status-badge status-alert';
        badge.innerHTML = `🔴 Infracción: ${texto}`;
        setTimeout(() => { badge.className = 'status-badge status-ok'; badge.innerHTML = '🟢 Monitoreo Activo'; }, 4000);
    }
}

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    agregarEventoVisual(tipo);
    
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.6);

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk})
        });
    } catch (e) { console.error(e); }
    setTimeout(() => enviandoAlerta = false, 4000); 
}

// --- ALGORITMO DE MIRADA ESTRICTA (GAZE RATIO) ---
let contMirada = 0;
const UMBRAL_MIRADA = 5; // ~0.15s: Apenas voltee, lo detecta

const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5}); 

faceMesh.onResults(async (res) => {
    // 1. Detección Cámara Tapada
    ctx.drawImage(video, 0, 0, 10, 10); 
    const data = ctx.getImageData(0, 0, 10, 10).data;
    let brillo = 0; for (let i = 0; i < data.length; i += 4) brillo += (data[i]+data[i+1]+data[i+2])/3;
    if ((brillo/100) < 15) { enviarAlerta("CÁMARA TAPADA", false); return; }

    // 2. Detección de Mirada por Ratio (Invariante a la distancia)
    if (res.multiFaceLandmarks && res.multiFaceLandmarks.length > 0) {
        const p = res.multiFaceLandmarks[0];
        
        // Ojo Izquierdo: 33 (interior), 133 (exterior), 468 (iris)
        const ancho_ojo = Math.abs(p[133].x - p[33].x);
        const distancia_iris = Math.abs(p[468].x - p[33].x);
        
        // Ratio: 0.5 es mirando al frente. < 0.35 izquierda, > 0.65 derecha.
        const ratio = distancia_iris / ancho_ojo;
        
        // Hacerlo ESTRICTO: Si sale del rango [0.40 - 0.60] es trampa.
        const desviada = ratio < 0.40 || ratio > 0.60;

        if (desviada) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) {
                enviarAlerta(`Mirada Desviada (Ratio: ${ratio.toFixed(2)})`);
                contMirada = 0;
            }
        } else { contMirada = 0; }
    }
});

// --- ALGORITMO DE OBJETOS (YOLOv8 ALTA SENSIBILIDAD) ---
let contCelular = 0;
const CONFIANZA_CELULAR = 0.28; // Extrema sensibilidad a celulares

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
        
        let celular = false;
        
        // Recorremos el tensor buscando la clase 67 (Teléfono)
        for (let i = 0; i < 8400; i++) {
            if (prob[71 * 8400 + i] > CONFIANZA_CELULAR) { celular = true; break; }
        }
        
        if (celular) {
            contCelular++;
            if (contCelular >= 2) { enviarAlerta("Celular Detectado"); contCelular = 0; }
        } else { contCelular = 0; }
        
    } catch(e) { console.error("Error YOLO:", e); }
}

// --- ARRANQUE ASÍNCRONO ---
const camera = new Camera(video, {
    onFrame: async () => {
        try {
            await faceMesh.send({image: video});
            frameCounter++;
            if (frameCounter % 5 === 0) await inferirYOLO(); // Analizar rápido (cada ~0.15s)
        } catch(e) {}
    },
    width: 640, height: 480
});

camera.start().then(() => {
    document.getElementById('estado').innerHTML = "⏳ Cámara OK. Cargando Tensor...";
    setTimeout(async () => {
        try {
            yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
            document.getElementById('estado').innerHTML = "🟢 Monitoreo Activo";
        } catch(e) { console.error(e); }
    }, 500);
});
