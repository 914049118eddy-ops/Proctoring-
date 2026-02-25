const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d');

let enviandoAlerta = false;
let yoloSession = null;

// --- PERSISTENCIA (Ajustada a tu petición) ---
let contMirada = 0;
const UMBRAL_MIRADA = 7; // ~0.2s (Súper estricto)
const SENSIBILIDAD_IRIS = 0.008; 

// --- DETECCIÓN DE CÁMARA TAPADA ---
async function checkCamara() {
    ctx.drawImage(video, 0, 0, 10, 10);
    const pix = ctx.getImageData(0, 0, 10, 10).data;
    let b = 0; for(let i=0; i<pix.length; i+=4) b += (pix[i]+pix[i+1]+pix[i+2])/3;
    if ((b/100) < 15) enviarAlerta("CÁMARA OBSTRUIDA", false);
}

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.5);
    await fetch('/api/alerta', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk, sala: DATOS_ALUMNO.sala})
    });
    setTimeout(() => enviandoAlerta = false, 5000);
}

// MediaPipe
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.8});
faceMesh.onResults(async (res) => {
    await checkCamara();
    if (res.multiFaceLandmarks?.length > 0) {
        const dX = Math.abs(res.multiFaceLandmarks[0][468].x - res.multiFaceLandmarks[0][33].x);
        if (dX < SENSIBILIDAD_IRIS) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) { enviarAlerta("Mirada Sospechosa"); contMirada = 0; }
        } else { contMirada = 0; }
    }
});

// Inicialización Segura
const camera = new Camera(video, {
    onFrame: async () => { await faceMesh.send({image: video}); },
    width: 640, height: 480
});

async function start() {
    try {
        yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx');
        await camera.start(); // Encendemos la cámara SOLO después de cargar la IA
        document.getElementById('estado').innerHTML = "🟢 Monitoreo Activo";
    } catch (e) { alert("Error al iniciar cámara: " + e); }
}
start();
