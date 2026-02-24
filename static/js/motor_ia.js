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
    document.getElementById('estado').className = 'status-badge status-alert';
    document.getElementById('estado').innerHTML = `🔴 Infracción: ${texto}`;
    setTimeout(() => {
        document.getElementById('estado').className = 'status-badge status-ok';
        document.getElementById('estado').innerHTML = '🟢 Monitoreo Estable';
    }, 3000);
}

async function enviarAlerta(tipo) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    agregarEventoVisual(tipo);
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.6);
    await fetch('/api/alerta', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img})
    });
    setTimeout(() => { enviandoAlerta = false; }, 5000);
}

// MediaPipe
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.5});
faceMesh.onResults((res) => {
    if (res.multiFaceLandmarks?.length > 0) {
        const d = Math.abs(res.multiFaceLandmarks[0][468].x - res.multiFaceLandmarks[0][33].x);
        if (d < 0.012) enviarAlerta("Mirada Desviada");
    }
});

// YOLO ONNX
async function initYOLO() {
    yoloSession = await ort.InferenceSession.create('/static/yolov8n.onnx', {executionProviders: ['wasm']});
}

async function runYOLO() {
    if (!yoloSession || enviandoAlerta) return;
    ctx.drawImage(video, 0, 0, 640, 640);
    const data = ctx.getImageData(0, 0, 640, 640).data;
    const input = new Float32Array(3 * 640 * 640);
    for (let i = 0; i < 640 * 640; i++) {
        input[i] = data[i*4]/255; input[640*640+i] = data[i*4+1]/255; input[2*640*640+i] = data[i*4+2]/255;
    }
    const output = await yoloSession.run({images: new ort.Tensor('float32', input, [1, 3, 640, 640])});
    const prob = output.output0.data;
    for (let i = 0; i < 8400; i++) {
        if (prob[8400 * 71 + i] > 0.55) { enviarAlerta("Celular Detectado"); break; }
    }
}

const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        if (Math.random() > 0.9) await runYOLO(); // Corre YOLO aleatoriamente para no saturar
    },
    width: 640, height: 480
});

initYOLO().then(() => camera.start());
