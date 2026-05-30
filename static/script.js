window.onload = function () {

const video = document.getElementById("video");
const output = document.getElementById("output");
const startBtn = document.getElementById("startBtn");

let streamReady = false;

// CAMERA
navigator.mediaDevices.getUserMedia({ video: true })
.then(stream => {
    video.srcObject = stream;
    streamReady = true;
});

// capture image
function captureImage() {
    if (!streamReady) return null;

    let canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;

    let ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    return canvas.toDataURL("image/jpeg");
}

// fake sensors
function getBlinkRate() { return Math.random() * 100; }
function getVoiceStress() { return Math.random() * 100; }

// voice
function speak(text) {
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

// graph
let stressData = [];
let labels = [];

const ctx = document.getElementById('chart').getContext('2d');

const chart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: labels,
        datasets: [{
            label: 'Stress Level',
            data: stressData,
            borderWidth: 2
        }]
    },
    options: {
        scales: { y: { min: 0, max: 100 } }
    }
});

let started = false;
let lastStress = null;
let lastSpoken = "";

function startAnalysis() {

    if (started) return;
    started = true;

    setInterval(() => {

        let image = captureImage();
        if (!image) return;

        let blink = getBlinkRate();
        let voice = getVoiceStress();

        fetch("/analyze", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ image, blink, voice })
        })
        .then(res => res.json())
        .then(data => {

            let trend = "Stable";

            if (lastStress !== null) {
                if (data.stress > lastStress) trend = "Increasing 📈";
                else trend = "Decreasing 📉";
            }

            lastStress = data.stress;

            output.innerHTML = `
                🧠 Stress: ${data.stress}% <br>
                📊 Level: ${data.level} <br>
                🚨 Risk: ${data.risk} <br>
                📈 Trend: ${trend} <br>
                📈 Accuracy: ${data.accuracy} <br><br>

                🧾 Reasons:<br>
                - ${data.reasons.join("<br>- ")} <br><br>

                💡 Suggestions:<br>
                - ${data.suggestions.join("<br>- ")}
            `;

            if (data.level !== lastSpoken) {
                if (data.stress > 70) speak("High stress detected");
                else if (data.stress > 40) speak("Moderate stress detected");
                else speak("You are doing well");

                lastSpoken = data.level;
            }

            stressData.push(data.stress);
            labels.push("");

            if (stressData.length > 20) {
                stressData.shift();
                labels.shift();
            }

            chart.update();
        })
        .catch(err => {
            output.innerHTML = "❌ Backend not responding";
        });

    }, 2000);
}

startBtn.addEventListener("click", startAnalysis);

};