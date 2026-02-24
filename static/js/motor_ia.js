// CONFIGURACIÓN SENSIBLE FIEE
const video = document.getElementById('video-alumno');
const canvas = document.getElementById('canvas-oculto');
const ctx = canvas.getContext('2d');

let contMirada = 0;
const UMBRAL_MIRADA = 10; // Reducido a ~0.3s para ser más estricto
const SENSIBILIDAD_IRIS = 0.009; // Rango más ajustado

async function detectarCamaraTapada() {
    ctx.drawImage(video, 0, 0, 10, 10); // Mini miniatura para CPU
    const data = ctx.getImageData(0, 0, 10, 10).data;
    let brilloTotal = 0;
    for (let i = 0; i < data.length; i += 4) {
        brilloTotal += (data[i] + data[i+1] + data[i+2]) / 3;
    }
    const brilloPromedio = brilloTotal / 100;
    return brilloPromedio < 15; // Si el brillo es < 15/255 está tapada
}

async function enviarAlerta(tipo, camOk = true) {
    if (enviandoAlerta) return;
    enviandoAlerta = true;
    
    ctx.drawImage(video, 0, 0, 640, 480);
    const img = canvas.toDataURL('image/jpeg', 0.5);

    await fetch('/api/alerta', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...DATOS_ALUMNO, tipo_falta: tipo, imagen_b64: img, camara_ok: camOk, materia: DATOS_ALUMNO.sala})
    });
    setTimeout(() => enviandoAlerta = false, 5000);
}

// MediaPipe con sensibilidad ajustada
const faceMesh = new FaceMesh({locateFile: (f) => `https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/${f}`});
faceMesh.setOptions({maxNumFaces: 1, refineLandmarks: true, minDetectionConfidence: 0.7}); // Más confianza requerida

faceMesh.onResults(async (res) => {
    // Check de cámara tapada cada frame
    if (await detectarCamaraTapada()) {
        enviarAlerta("CÁMARA TAPADA/OSCURA", false);
    }

    if (res.multiFaceLandmarks?.length > 0) {
        const iris = res.multiFaceLandmarks[0];
        const dX = Math.abs(iris[468].x - iris[33].x);
        
        // Rango más estricto (0.009) y tiempo más corto (10 frames)
        if (dX < SENSIBILIDAD_IRIS) {
            contMirada++;
            if (contMirada > UMBRAL_MIRADA) {
                enviarAlerta("Desviación de Mirada");
                contMirada = 0;
            }
        } else { contMirada = 0; }
    }
});

// YOLO corre cada 8 frames (~0.25s) para detectar el teléfono al instante
const camera = new Camera(video, {
    onFrame: async () => {
        await faceMesh.send({image: video});
        if (frameCounter % 8 === 0) await inferirYOLO();
        frameCounter++;
    }
});
