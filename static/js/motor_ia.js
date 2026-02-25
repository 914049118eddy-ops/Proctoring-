// ==========================================
// MOTOR IA V8.0 - FIEE UNI (YOLO CORREGIDO Y UNIFICADO)
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
        await fetch('/api/alerta_ia', { // Ruta actualizada a la nueva API POO
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk})
        });
    } catch (e) { console.error(e); }
    setTimeout(() => enviandoAlerta = false, 4000); 
}

// --- 2. MEDIAPIPE (MIRADA Y CÁMARA TAPADA) ---
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

// --- 3. YOLOv8 CORREGIDO (DETECCIÓN DE CELULARES Y LIBROS) ---
let contObjeto = 0;

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
        
        // Búsqueda del tensor máximo para celular (clase 67 -> índice 71) y libro (clase 73 -> índice 77)
        let max_celular_conf = 0;
        let max_libro_conf = 0;
        
        for (let i = 0; i < 8400; i++) {
            const conf_celular = prob[71 * 8400 + i];
            const conf_libro = prob[77 * 8400 + i];
            
            if (conf_celular > max_celular_conf) max_celular_conf = conf_celular;
            if (conf_libro > max_libro_conf) max_libro_conf = conf_libro;
        }

        // Puedes ver la confianza real en tu consola pulsando F12
        // console.log("Confianza Celular:", max_celular_conf, "| Libro:", max_libro_conf);
        
        // Umbral bajado a 0.20 para asegurar la detección en webcams
        if (max_celular_conf > 0.20) {
            contObjeto++;
            if (contObjeto >= 2) { enviarAlerta("Teléfono Celular Detectado"); contObjeto = 0; }
        } else if (max_libro_conf > 0.25) {
            contObjeto++;
            if (contObjeto >= 2) { enviarAlerta("Libro/Apuntes Detectados"); contObjeto = 0; }
        } else {
            contObjeto = 0;
        }
        
    } catch(e) { console.error("Error YOLO:", e); }
}

// --- 4. ARRANQUE ASÍNCRONO ---
const camera = new Camera(video, {
    onFrame: async () => {
        try {
            await faceMesh.send({image: video});
            frameCounter++;
            if (frameCounter % 5 === 0) await inferirYOLO(); // Analizar rápido
        } catch(e) {}
    },
    width: 640, height: 480
});

camera.start().then(() => {
    setTimeout(async () => {
        try {
            yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
            document.getElementById('estado').innerHTML = "🟢 Monitoreo Activo";
            document.getElementById('estado').style.color = '#10b981';
            document.getElementById('estado').style.borderColor = '#10b981';
        } catch(e) { console.error(e); }
    }, 500);
});
