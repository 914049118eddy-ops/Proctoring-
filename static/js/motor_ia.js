// ==========================================
// MOTOR IA V9.0 - FIEE UNI (DEBUG MODE + YOLO RESCUE)
// ==========================================
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

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
        badge.innerHTML = `🔴 Infracción: ${texto}`;
        setTimeout(() => { 
            badge.className = 'status-badge status-ok'; 
            badge.style.color = '#10b981';
            badge.style.borderColor = '#10b981';
            badge.innerHTML = '🟢 Monitoreo Activo'; 
        }, 4000);
    }
}

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    agregarEventoVisual(tipo);
    
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.6);

    try {
        await fetch('/api/alerta_ia', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk})
        });
    } catch (e) { console.error(e); }
    setTimeout(() => enviandoAlerta = false, 4000); 
}

let contMirada = 0;
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5}); 

faceMesh.onResults(async (res) => {
    ctx.drawImage(video, 0, 0, 10, 10); 
    const data = ctx.getImageData(0, 0, 10, 10).data;
    let brillo = 0; for (let i = 0; i < data.length; i += 4) brillo += (data[i]+data[i+1]+data[i+2])/3;
    if ((brillo/100) < 15) { enviarAlerta("CÁMARA TAPADA", false); return; }

    if (res.multiFaceLandmarks && res.multiFaceLandmarks.length > 0) {
        const p = res.multiFaceLandmarks[0];
        const ancho_ojo = Math.abs(p[133].x - p[33].x);
        const distancia_iris = Math.abs(p[468].x - p[33].x);
        const ratio = distancia_iris / ancho_ojo;
        
        if (ratio < 0.40 || ratio > 0.60) {
            contMirada++;
            if (contMirada > 5) { enviarAlerta("Mirada Desviada"); contMirada = 0; }
        } else { contMirada = 0; }
    }
});

let contCelular = 0;
// Bajamos drásticamente el umbral para asegurar que lo detecte.
const CONFIANZA_MINIMA = 0.15; 

async function inferirYOLO() {
    if (!yoloSession || enviandoAlerta) return;
    
    // 1. Preprocesamiento de la imagen para YOLO
    ctx.drawImage(video, 0, 0, 640, 640);
    const data = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = data[i*4] / 255.0;              // Canal R
        input[640*640+i] = data[i*4+1] / 255.0;    // Canal G
        input[2*640*640+i] = data[i*4+2] / 255.0;  // Canal B
    }
    
    try {
        const tensor = new ort.Tensor('float32', input, [1, 3, 640, 640]);
        const output = await yoloSession.run({images: tensor});
        const prob = output.output0.data; // Array plano de 1 * 84 * 8400
        
        let celular = false;
        
        // MODO DEBUG: Vamos a ver qué detecta globalmente
        let max_overall_conf = 0;
        let best_class = -1;
        
        for (let clase = 4; clase < 84; clase++) { // Las primeras 4 filas son coordenadas (X,Y,W,H)
            for (let i = 0; i < 8400; i++) {
                const conf = prob[clase * 8400 + i];
                if (conf > max_overall_conf) {
                    max_overall_conf = conf;
                    best_class = clase - 4; // Ajustamos para obtener el ID real de COCO (0 a 79)
                }
            }
        }
        
        // Imprime en la consola del navegador (F12) lo que la IA ve con más confianza en ese momento
        console.log(`[YOLO Debug] Mejor Detección -> Clase: ${best_class} | Confianza: ${(max_overall_conf * 100).toFixed(2)}%`);

        // Evaluación específica de Celular (Clase 67 -> fila 71)
        for (let i = 0; i < 8400; i++) {
            if (prob[71 * 8400 + i] > CONFIANZA_MINIMA) { 
                celular = true; 
                break; 
            }
        }
        
        if (celular) {
            contCelular++;
            if (contCelular >= 2) { enviarAlerta("Teléfono Celular Detectado"); contCelular = 0; }
        } else { 
            contCelular = 0; 
        }
        
    } catch(e) { console.error("Error YOLO:", e); }
}

const camera = new Camera(video, {
    onFrame: async () => {
        try {
            await faceMesh.send({image: video});
            frameCounter++;
            if (frameCounter % 5 === 0) await inferirYOLO();
        } catch(e) {}
    },
    width: 640, height: 480
});

camera.start().then(() => {
    setTimeout(async () => {
        try {
            // Inicialización de YOLO sin forzar hilos para evitar cuelgues
            yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
            const badge = document.getElementById('estado');
            if(badge) {
                badge.innerHTML = "🟢 Monitoreo Activo";
                badge.style.color = '#10b981';
                badge.style.borderColor = '#10b981';
            }
        } catch(e) { console.error("Fallo al cargar modelo ONNX:", e); }
    }, 500);
});
