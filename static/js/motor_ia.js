// ==========================================
// MOTOR IA V6.0 - FIEE UNI (ALGORITMO LOCAL PORTADO A EDGE)
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

// --- 1. PRISIÓN DIGITAL ---
window.addEventListener('blur', () => enviarAlerta("Cambio de Pestaña (Posible Fraude)", true));
document.addEventListener('contextmenu', e => e.preventDefault());

// --- 2. COMUNICACIÓN CON PYTHON ---
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

// --- 3. ALGORITMO DE MIRADA (Extraído de tu clase DetectorMirada) ---
let contMirada = 0;
const UMBRAL_MIRADA = 10; 

const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5}); 

faceMesh.onResults(async (res) => {
    // Detección de cámara tapada (brillo)
    ctx.drawImage(video, 0, 0, 10, 10); 
    const data = ctx.getImageData(0, 0, 10, 10).data;
    let brillo = 0; for (let i = 0; i < data.length; i += 4) brillo += (data[i]+data[i+1]+data[i+2])/3;
    if ((brillo/100) < 15) { enviarAlerta("CÁMARA TAPADA", false); return; }

    if (res.multiFaceLandmarks && res.multiFaceLandmarks.length > 0) {
        const puntos = res.multiFaceLandmarks[0];
        
        // TU LÓGICA MATEMÁTICA EXACTA
        const mira_izquierda = Math.abs(puntos[468].x - puntos[33].x) < 0.012;
        const mira_derecha = Math.abs(puntos[468].x - puntos[133].x) < 0.012;
        const mira_arriba = (puntos[159].y - puntos[468].y) > 0.018;
        
        const desviada = mira_izquierda || mira_derecha || mira_arriba;

        if (desviada) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) {
                enviarAlerta("Mirada Desviada (Izquierda/Derecha/Arriba)");
                contMirada = 0;
            }
        } else { contMirada = 0; }
    }
});

// --- 4. ALGORITMO DE OBJETOS (YOLOv8) ---
let contCelular = 0;
let contLibro = 0;

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
        let libro = false;
        
        // Tensor de YOLOv8: Las filas de clases empiezan en el índice 4. 
        // Celular (67) -> Fila 71. Libro (73) -> Fila 77.
        for (let i = 0; i < 8400; i++) {
            if (prob[71 * 8400 + i] > 0.40) celular = true; // Confianza bajada a 0.40 para webcam
            if (prob[77 * 8400 + i] > 0.40) libro = true;
        }
        
        if (celular) {
            contCelular++;
            if (contCelular >= 3) { enviarAlerta("Celular Detectado"); contCelular = 0; }
        } else { contCelular = 0; }

        if (libro) {
            contLibro++;
            if (contLibro >= 3) { enviarAlerta("Libro/Apuntes Detectados"); contLibro = 0; }
        } else { contLibro = 0; }
        
    } catch(e) { console.error("Error YOLO:", e); }
}

// --- 5. ARRANQUE ASÍNCRONO ---
const camera = new Camera(video, {
    onFrame: async () => {
        try {
            await faceMesh.send({image: video});
            frameCounter++;
            if (frameCounter % 5 === 0) await inferirYOLO(); // Analizar objetos rápido (cada ~0.15s)
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
