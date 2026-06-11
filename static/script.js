window.onload = function () {

    // ─── ELEMENTS ───────────────────────────────────
    const video        = document.getElementById("video");
    const startBtn     = document.getElementById("startBtn");
    const stressNumber = document.getElementById("stressNumber");
    const stressLabel  = document.getElementById("stressLabel");
    const stressTrend  = document.getElementById("stressTrend");
    const riskCard     = document.getElementById("riskCard");
    const riskIcon     = document.getElementById("riskIcon");
    const riskText     = document.getElementById("riskText");
    const reasonsList  = document.getElementById("reasonsList");
    const suggsList    = document.getElementById("suggestionsList");
    const statusChip   = document.getElementById("statusChip");
    const videoOverlay = document.getElementById("videoOverlay");
    const camInactive  = document.getElementById("camInactive");
    const toast        = document.getElementById("toast");

    // Stat elements
    const sessionTimeEl  = document.getElementById("sessionTime");
    const readingCountEl = document.getElementById("readingCount");
    const avgStressEl    = document.getElementById("avgStress");
    const peakStressEl   = document.getElementById("peakStress");

    // Ring arc elements
    const blinkArc = document.getElementById("blinkArc");
    const voiceArc = document.getElementById("voiceArc");
    const faceArc  = document.getElementById("faceArc");

    const blinkVal = document.getElementById("blinkVal");
    const voiceVal = document.getElementById("voiceVal");
    const faceVal  = document.getElementById("faceVal");

    // SVG needle / arc
    const stressArc = document.getElementById("stressArc");
    const needle    = document.getElementById("needle");

    // ─── CAMERA ─────────────────────────────────────
    let streamReady = false;

    navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        .then(stream => {
            video.srcObject = stream;
            streamReady = true;
            camInactive.classList.add("hidden");
            showToast("📷 Camera connected");
        })
        .catch(() => showToast("❌ Camera access denied"));

    // ─── CHART ──────────────────────────────────────
    const chartCtx = document.getElementById("chart").getContext("2d");
    const stressHistory = [];
    const labels = [];

    const chart = new Chart(chartCtx, {
        type: "line",
        data: {
            labels,
            datasets: [{
                label: "Stress %",
                data: stressHistory,
                borderColor: "rgba(56,189,248,0.9)",
                backgroundColor: "rgba(56,189,248,0.06)",
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 3,
                pointBackgroundColor: "rgba(56,189,248,1)"
            }]
        },
        options: {
            animation: { duration: 500 },
            scales: {
                y: {
                    min: 0, max: 100,
                    grid: { color: "rgba(255,255,255,0.04)" },
                    ticks: { color: "#64748b", font: { family: "'DM Mono', monospace", size: 10 } }
                },
                x: {
                    grid: { display: false },
                    ticks: { display: false }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: "#0c1525",
                    borderColor: "rgba(56,189,248,0.3)",
                    borderWidth: 1,
                    titleColor: "#64748b",
                    bodyColor: "#e2e8f0",
                    callbacks: { label: ctx => ` Stress: ${ctx.parsed.y}%` }
                }
            }
        }
    });

    // ─── STATE ──────────────────────────────────────
    let started        = false;
    let lastStress     = null;
    let lastSpoken     = "";
    let readingCount   = 0;
    let stressSum      = 0;
    let peakVal        = 0;
    let sessionStart   = null;
    let timerInterval  = null;

    // ─── HELPERS ────────────────────────────────────

    function captureImage() {
        if (!streamReady) return null;
        const canvas = document.createElement("canvas");
        canvas.width  = video.videoWidth  || 640;
        canvas.height = video.videoHeight || 480;
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL("image/jpeg", 0.8);
    }

    // Fake sensors — replace with real microphone / blink detection
    function getBlinkRate()   { return Math.random() * 100; }
    function getVoiceStress() { return Math.random() * 100; }

    function speak(text) {
        const u = new SpeechSynthesisUtterance(text);
        u.rate = 0.95; u.pitch = 1.05;
        window.speechSynthesis.speak(u);
    }

    function showToast(msg) {
        toast.textContent = msg;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 3000);
    }

    // Convert 0-100 value to ring stroke-dashoffset (214 = full circumference)
    function setRing(arc, val) {
        const pct = Math.min(100, Math.max(0, val)) / 100;
        const offset = 214 - pct * 214;
        arc.style.strokeDashoffset = offset;
        // Dynamic color based on value
        if (val > 70) arc.style.stroke = "var(--danger)";
        else if (val > 45) arc.style.stroke = "var(--warn)";
        else arc.style.stroke = "";
    }

    // Update the big half-arc meter
    function setMeter(pct) {
        // Arc total length ~283 for that path
        const offset = 283 - (pct / 100) * 283;
        stressArc.style.strokeDashoffset = offset;

        // Needle: -90deg = 0%, +90deg = 100%
        const angle = -90 + (pct / 100) * 180;
        needle.setAttribute("transform", `rotate(${angle}, 110, 120)`);
    }

    function getStressClass(score) {
        if (score < 30) return "stress-low";
        if (score < 60) return "stress-medium";
        return "stress-high";
    }

    function startSessionTimer() {
        sessionStart = Date.now();
        timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
            const m = Math.floor(elapsed / 60);
            const s = elapsed % 60;
            sessionTimeEl.textContent = `${m}:${s.toString().padStart(2, "0")}`;
        }, 1000);
    }

    // ─── MAIN ANALYSIS LOOP ──────────────────────────
    function startAnalysis() {
        if (started) return;
        started = true;

        startBtn.textContent = "⏹ Stop Analysis";
        startBtn.classList.add("running");
        statusChip.textContent = "Running";
        statusChip.classList.add("running");
        videoOverlay.classList.add("active");
        startSessionTimer();
        showToast("🧠 Analysis started");

        setInterval(() => {
            const image = captureImage();
            if (!image) return;

            const blink = getBlinkRate();
            const voice = getVoiceStress();

            // Update rings immediately (don't wait for backend)
            setRing(blinkArc, blink);
            setRing(voiceArc, voice);
            blinkVal.textContent = Math.round(blink);
            voiceVal.textContent = Math.round(voice);

            fetch("/analyze", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image, blink, voice })
            })
            .then(res => res.json())
            .then(data => {
                if (data.error) { showToast("⚠️ Backend error"); return; }

                const s = data.stress;
                readingCount++;
                stressSum += s;
                if (s > peakVal) peakVal = s;

                // Face ring (from backend face score)
                const faceScore = Math.round((s / 0.4) - (blink * 0.3 / 0.4) - (voice * 0.3 / 0.4));
                setRing(faceArc, Math.min(100, Math.max(0, faceScore)));
                faceVal.textContent = Math.min(100, Math.max(0, Math.round(faceScore)));

                // Session stats
                readingCountEl.textContent = readingCount;
                avgStressEl.textContent    = Math.round(stressSum / readingCount) + "%";
                peakStressEl.textContent   = Math.round(peakVal) + "%";

                // Trend
                let trend = "";
                if (lastStress !== null) {
                    trend = s > lastStress ? "📈 Increasing" : "📉 Decreasing";
                }
                lastStress = s;

                // Big number
                stressNumber.textContent = Math.round(s) + "%";
                stressNumber.className = "stress-number " + getStressClass(s);
                stressLabel.textContent = data.level;
                stressTrend.textContent = trend;
                setMeter(s);

                // Risk card
                riskCard.className = "card risk-card";
                if (s < 30)      { riskCard.classList.add("ok");   riskIcon.textContent = "🟢"; }
                else if (s < 60) { riskCard.classList.add("warn"); riskIcon.textContent = "🟡"; }
                else             { riskCard.classList.add("high"); riskIcon.textContent = "🔴"; }
                riskText.textContent = data.risk;

                // Reasons
                reasonsList.innerHTML = data.reasons.map(r =>
                    `<li>⚡ ${r}</li>`
                ).join("");

                // Suggestions
                suggsList.innerHTML = data.suggestions.map(s =>
                    `<li>💡 ${s}</li>`
                ).join("");

                // Voice alert
                if (data.level !== lastSpoken) {
                    if (s > 70)      speak("High stress detected. Please take a break.");
                    else if (s > 40) speak("Moderate stress detected.");
                    else             speak("You are doing well. Keep it up.");
                    lastSpoken = data.level;
                }

                // Chart
                stressHistory.push(Math.round(s));
                labels.push("");
                if (stressHistory.length > 20) { stressHistory.shift(); labels.shift(); }
                chart.update();
            })
            .catch(() => showToast("❌ Backend not responding"));

        }, 2000);
    }

    startBtn.addEventListener("click", startAnalysis);
};