// ==========================================
// MOTOR IA V10.0 - FIEE UNI (TENSOR BOUNDING BOX RENDERING)
// ==========================================
const video = document.getElementById('video-alumno');
const canvasOculto = document.getElementById('canvas-oculto');
const ctxOculto = canvasOculto.getContext('2d', { willReadFrequently: true });
const HEARTBEAT_INTERVAL = 30000;

const overlayCanvas = document.getElementById('overlay-ia');
const ctxOverlay = overlayCanvas ? overlayCanvas.getContext('2d') : null;

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

// --- 1. PRISIÓN DIGITAL ---
window.addEventListener('blur', () => enviarAlerta("Cambio de Pestaña", true));
document.addEventListener('contextmenu', e => e.preventDefault());

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
        badge.style.color = '#ef4444';
        badge.style.borderColor = '#ef4444';
        badge.style.background = '#fef2f2';
        badge.innerHTML = `🔴 Infracción: ${texto}`;
        setTimeout(() => { 
            badge.className = 'status-badge status-ok'; 
            badge.style.color = '#10b981';
            badge.style.borderColor = '#10b981';
            badge.style.background = '#f0fdf4';
            badge.innerHTML = '🟢 Auditoría Activa'; 
        }, 4000);
    }
}

// --- HEARTBEAT ---
setInterval(async () => {
    try {
        await fetch('/api/heartbeat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({uid: DATOS_ALUMNO.uid, sala: DATOS_ALUMNO.sala})
        });
    } catch (e) { console.warn("Intermitencia de red detectada."); }
}, HEARTBEAT_INTERVAL);

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    agregarEventoVisual(tipo);
    
    ctxOculto.drawImage(video, 0, 0, 640, 480);
    const img = canvasOculto.toDataURL('image/jpeg', 0.6);

    try {
        const response = await fetch('/api/alerta_ia', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk})
        });
        
        const data = await response.json();
        
        if (data.estado === "BLOQUEADO") {
            document.body.innerHTML = `
                <div style="display:flex; justify-content:center; align-items:center; height:100vh; background:#fef2f2; font-family:sans-serif;">
                    <div style="background:white; padding:50px; border-radius:12px; box-shadow:0 10px 15px -3px rgb(0 0 0 / 0.1); text-align:center; border-top:6px solid #ef4444;">
                        <h1 style="color:#ef4444; margin-top:0; font-weight:800;">EXAMEN ANULADO</h1>
                        <p style="color:#64748b; font-size:16px;">Has excedido el límite de infracciones permitidas (Multa IA).</p>
                        <p style="font-size:12px; color:#94a3b8;">Tu sesión ha sido bloqueada y el docente ha sido notificado.</p>
                        <button onclick="location.href='/'" style="margin-top:20px; padding:10px 20px; background:#ef4444; color:white; border:none; border-radius:5px; cursor:pointer;">Cerrar</button>
                    </div>
                </div>
            `;
            camera.stop();
            return; 
        }
    } catch (e) { console.error(e); }

    setTimeout(() => enviandoAlerta = false, 4000); 
}

// --- 2. MEDIAPIPE ---
let contMirada = 0;

const faceMesh = new FaceMesh({
    locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`
});

faceMesh.setOptions({
    maxNumFaces: 1,
    refineLandmarks: true,
    minDetectionConfidence: 0.5
});

faceMesh.onResults(async (res) => {
    ctxOculto.drawImage(video, 0, 0, 10, 10);
    const data = ctxOculto.getImageData(0, 0, 10, 10).data;

    let brillo = 0;
    for (let i = 0; i < data.length; i += 4)
        brillo += (data[i]+data[i+1]+data[i+2])/3;

    if ((brillo/100) < 15) {
        enviarAlerta("CÁMARA TAPADA", false);
        return;
    }

    if (res.multiFaceLandmarks && res.multiFaceLandmarks.length > 0) {
        const p = res.multiFaceLandmarks[0];
        const ancho_ojo = Math.abs(p[133].x - p[33].x);
        const distancia_iris = Math.abs(p[468].x - p[33].x);
        const ratio = distancia_iris / ancho_ojo;

        if (ratio < 0.40 || ratio > 0.60) {
            contMirada++;
            if (contMirada > 5) {
                enviarAlerta("Mirada Desviada");
                contMirada = 0;
            }
        } else {
            contMirada = 0;
        }
    }
});

// --- 3. YOLO (SOLO CELULAR) ---
let contCelular = 0;
const CONFIANZA_MINIMA = 0.60;

function ajustarCanvasOverlay() {
    if (overlayCanvas && video.videoWidth > 0) {
        overlayCanvas.width = video.clientWidth;
        overlayCanvas.height = video.clientHeight;
    }
}

async function inferirYOLO() {
    if (!yoloSession || enviandoAlerta) return;

    ctxOculto.drawImage(video, 0, 0, 640, 640);
    const data = ctxOculto.getImageData(0, 0, 640, 640).data;

    const input = new Float32Array(3 * 640 * 640);
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = data[i*4] / 255.0;
        input[640*640+i] = data[i*4+1] / 255.0;
        input[2*640*640+i] = data[i*4+2] / 255.0;
    }

    try {
        const tensor = new ort.Tensor('float32', input, [1, 3, 640, 640]);
        const output = await yoloSession.run({images: tensor});
        const prob = output.output0.data;

        let max_confianza = 0;
        let mejor_caja_idx = -1;
        let objeto_detectado = null;

        for (let i = 0; i < 8400; i++) {
            const conf_celular = prob[67 * 8400 + i];

            if (conf_celular > CONFIANZA_MINIMA && conf_celular > max_confianza) {
                max_confianza = conf_celular;
                mejor_caja_idx = i;
                objeto_detectado = "Celular";
            }
        }

        ajustarCanvasOverlay();
        ctxOverlay.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

        if (mejor_caja_idx !== -1) {
            const cx = prob[0 * 8400 + mejor_caja_idx];
            const cy = prob[1 * 8400 + mejor_caja_idx];
            const w  = prob[2 * 8400 + mejor_caja_idx];
            const h  = prob[3 * 8400 + mejor_caja_idx];

            const escalaX = overlayCanvas.width / 640;
            const escalaY = overlayCanvas.height / 640;

            const x_pixel = (cx - w/2) * escalaX;
            const y_pixel = (cy - h/2) * escalaY;

            ctxOverlay.strokeStyle = "#800000";
            ctxOverlay.setLineDash([5,5]);
            ctxOverlay.lineWidth = 2;
            ctxOverlay.strokeRect(x_pixel, y_pixel, w * escalaX, h * escalaY);

            ctxOverlay.fillStyle = "#800000";
            ctxOverlay.fillRect(x_pixel, y_pixel - 20, 100, 20);
            ctxOverlay.fillStyle = "white";
            ctxOverlay.fillText(`${objeto_detectado}`, x_pixel + 5, y_pixel - 5);

            contCelular++;
            if (contCelular >= 2) {
                enviarAlerta(`${objeto_detectado} Detectado`);
                contCelular = 0;
            }
        } else {
            contCelular = 0;
        }

    } catch(e) {
        console.error("Error Matemático YOLO:", e);
    }
}

// --- 4. ARRANQUE ---
const camera = new Camera(video, {
    onFrame: async () => {
        try {
            await faceMesh.send({image: video});
            frameCounter++;
            if (frameCounter % 5 === 0) await inferirYOLO();
        } catch(e){}
    },
    width: 640,
    height: 480
});

camera.start().then(() => {
    setTimeout(async () => {
        try {
            yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders:['wasm']});
            const badge = document.getElementById('estado');
            if(badge){
                badge.innerHTML = "🟢 Auditoría Activa";
                badge.style.color = '#10b981';
                badge.style.borderColor = '#10b981';
                badge.style.background = '#f0fdf4';
            }
        } catch(e){ console.error(e); }
    }, 500);
});
