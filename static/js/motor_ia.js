const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

let enviandoAlerta = false;
let yoloSession = null;
let frameCounter = 0;

// CONFIGURACIÓN ESTRICTA
let contMirada = 0;
const UMBRAL_MIRADA = 8; // ~0.25s (Súper rápido)
const SENSIBILIDAD_IRIS = 0.0085; // Rango milimétrico

async function detectarCamaraSaboteada() {
    ctx.drawImage(video, 0, 0, 10, 10);
    const pix = ctx.getImageData(0, 0, 10, 10).data;
    let brillo = 0;
    for (let i = 0; i < pix.length; i += 4) {
        brillo += (pix[i] + pix[i+1] + pix[i+2]) / 3;
    }
    return (brillo / 100) < 12; // Umbral de oscuridad
}

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.5);

    try {
        await fetch('/api/alerta', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                uid: DATOS_ALUMNO.uid,
                nombre: DATOS_ALUMNO.nombre,
                sala: DATOS_ALUMNO.sala,
                tipo_falta: tipo,
                imagen_b64: img,
                camara_ok: camOk
            })
        });
    } catch (e) { console.error(e); }
    setTimeout(() => enviandoAlerta = false, 4000);
}

const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.8});

faceMesh.onResults(async (res) => {
    if (await detectarCamaraSaboteada()) {
        enviarAlerta("CÁMARA OBSTRUIDA", false);
        return;
    }

    if (res.multiFaceLandmarks?.length > 0) {
        const iris = res.multiFaceLandmarks[0];
        const dX = Math.abs(iris[468].x - iris[33].x);
        
        if (dX < SENSIBILIDAD_IRIS) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) {
                enviarAlerta("Desviación de Mirada Estricta");
                contMirada = 0;
            }
        } else { contMirada = 0; }
    }
});

async function inferirYOLO() {
    if (!yoloSession || enviandoAlerta) return;
    ctx.drawImage(video, 0, 0, 640, 640);
    const imageData = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = imageData[i*4]/255;
        input[640*640+i] = imageData[i*4+1]/255;
        input[2*640*640+i] = imageData[i*4+2]/255;
    }
    const output = await yoloSession.run({images: new ort.Tensor('float32', input, [1, 3, 640, 640])});
    const data = output.output0.data;
    for (let i = 0; i < 8400; i++) {
        if (data[8400 * 71 + i] > 0.5) { // Clase 67: Cell Phone
            enviarAlerta("Teléfono Detectado");
            break;
        }
    }
}

const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        if (frameCounter % 7 === 0) await inferirYOLO();
        frameCounter++;
    }
});

ort.InferenceSession.create('/static/yolov8n.onnx').then(s => {
    yoloSession = s;
    camera.start().then(() => document.getElementById('estado').innerHTML = "🟢 En Línea");
});
