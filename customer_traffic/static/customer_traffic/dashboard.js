
const maxPoints = 300;
const trafficLabels = [];
const uploadData = [];
const downloadData = [];

let historyLoaded = false;
let historyRequested = false;
let trafficRequestInProgress = false;

// MikroTik-style graph — original appearance preserved.
const chart = new Chart(document.getElementById("trafficChart"), {
    type: "line",
    data: {
        labels: trafficLabels,
        datasets: [
            {
                label: "Upload",
                data: uploadData,
                borderColor: "#22c55e",
                backgroundColor: "rgba(34, 197, 94, 0.35)",
                borderWidth: 1,
                fill: true,
                tension: 0,
                pointRadius: 0,
                pointHoverRadius: 4
            },
            {
                label: "Download",
                data: downloadData,
                borderColor: "#3b82f6",
                backgroundColor: "rgba(59, 130, 246, 0.35)",
                borderWidth: 1,
                fill: true,
                tension: 0,
                pointRadius: 0,
                pointHoverRadius: 4
            }
        ]
    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: {
            intersect: false,
            mode: "index"
        },
        scales: {
            x: {
                grid: {
                    color: "rgba(255,255,255,0.08)",
                    drawBorder: false
                },
                ticks: {
                    color: "#9ca3af",
                    maxTicksLimit: 8
                }
            },
            y: {
                beginAtZero: true,
                grid: {
                    color: "rgba(255,255,255,0.08)",
                    drawBorder: false
                },
                ticks: {
                    color: "#9ca3af",
                    callback: value => formatChartSpeed(value)
                }
            }
        },
        plugins: {
            legend: {
                display: false
            },
            tooltip: {
                backgroundColor: "#030712",
                titleColor: "#ffffff",
                bodyColor: "#ffffff",
                borderColor: "#374151",
                borderWidth: 1,
                displayColors: true,
                callbacks: {
                    label: context =>
                        context.dataset.label + ": " +
                        formatChartSpeed(context.raw)
                }
            }
        }
    }
});

// Format speed for the cards.
function formatSpeed(speed) {
    speed = Math.max(0, Number(speed) || 0);

    if (speed >= 1000000000) {
        return {
            value: (speed / 1000000000).toFixed(2),
            unit: "Gbps"
        };
    }

    if (speed >= 1000000) {
        return {
            value: (speed / 1000000).toFixed(2),
            unit: "Mbps"
        };
    }

    if (speed >= 1000) {
        return {
            value: (speed / 1000).toFixed(2),
            unit: "Kbps"
        };
    }

    return {
        value: Math.round(speed),
        unit: "bps"
    };
}

// Format graph values.
function formatChartSpeed(speed) {
    speed = Math.max(0, Number(speed) || 0);

    if (speed >= 1000000000) {
        return (speed / 1000000000).toFixed(1) + " Gbps";
    }

    if (speed >= 1000000) {
        return (speed / 1000000).toFixed(1) + " Mbps";
    }

    if (speed >= 1000) {
        return (speed / 1000).toFixed(1) + " Kbps";
    }

    return Math.round(speed) + " bps";
}

// Update connection status.
function setConnectionStatus(online) {
    document.getElementById("status-dot").className = online
        ? "w-3 h-3 bg-green-500 rounded-full"
        : "w-3 h-3 bg-red-500 rounded-full";

    document.getElementById("status-text").textContent = online
        ? "Online"
        : "Connection unavailable";

    document.getElementById("status-text").className = online
        ? "text-sm text-green-600"
        : "text-sm text-red-600";
}

// Load historical graph data only once.
function loadHistory(history) {
    if (historyLoaded || !Array.isArray(history)) {
        return;
    }

    trafficLabels.length = 0;
    uploadData.length = 0;
    downloadData.length = 0;

    history.slice(-maxPoints).forEach(item => {
        const date = new Date(item.time);

        const time =
            date.getHours().toString().padStart(2, "0") + ":" +
            date.getMinutes().toString().padStart(2, "0") + ":" +
            date.getSeconds().toString().padStart(2, "0");

        trafficLabels.push(time);
        uploadData.push(Number(item.upload) || 0);
        downloadData.push(Number(item.download) || 0);
    });

    historyLoaded = true;
}

// Poll live traffic.

const POLL_INTERVAL_MS = 1000;
const MAX_RETRY_INTERVAL_MS = 15000;
const REQUEST_TIMEOUT_MS = 8000;
const POLL_JITTER_MS = 200;

let pollTimer = null;
let consecutiveFailures = 0;

// Schedule the next request without allowing overlapping polls.
function scheduleNextPoll(delay) {
    clearTimeout(pollTimer);

    if (document.hidden) {
        return;
    }

    pollTimer = setTimeout(updateTraffic, delay);
}

// Poll live traffic.
async function updateTraffic() {
    if (document.hidden || trafficRequestInProgress) {
        return;
    }

    trafficRequestInProgress = true;

    let timeoutId = null;
    let controller = null;

    try {
        const requestingHistory = !historyRequested;
        const url = requestingHistory
            ? "/api/traffic/?history=1"
            : "/api/traffic/";

        controller = new AbortController();

        timeoutId = setTimeout(() => {
            controller.abort();
        }, REQUEST_TIMEOUT_MS);

        const response = await fetch(url, {
            cache: "no-store",
            signal: controller.signal,
            headers: {
                "Accept": "application/json"
            }
        });

        if (!response.ok) {
            throw new Error("Traffic API error: " + response.status);
        }

        const data = await response.json();

        function isValidSpeed(value) {
            return (
                typeof value === "number" &&
                Number.isFinite(value) &&
                value >= 0
            );
        }

        if (
            !data ||
            typeof data !== "object" ||
            !isValidSpeed(data.upload) ||
            !isValidSpeed(data.download)
        ) {
            throw new Error("Invalid traffic data");
        }

        // Request history only once after the first successful response.
        if (requestingHistory) {
            historyRequested = true;

            if (Array.isArray(data.history)) {
                loadHistory(data.history);
            }
        }

        const upload = formatSpeed(data.upload);
        const download = formatSpeed(data.download);

        document.getElementById("upload").textContent = upload.value;
        document.getElementById("upload-unit").textContent = upload.unit;

        document.getElementById("download").textContent = download.value;
        document.getElementById("download-unit").textContent = download.unit;

        document.getElementById("ac-name").textContent =
            data.ac || "Connected";

        setConnectionStatus(true);

        // Add the latest live sample.
        const now = new Date();
        const time =
            now.getHours().toString().padStart(2, "0") + ":" +
            now.getMinutes().toString().padStart(2, "0") + ":" +
            now.getSeconds().toString().padStart(2, "0");

        trafficLabels.push(time);
        uploadData.push(Number(data.upload));
        downloadData.push(Number(data.download));

        while (trafficLabels.length > maxPoints) {
            trafficLabels.shift();
            uploadData.shift();
            downloadData.shift();
        }

        chart.update("none");

        // Reset retry delay after a successful request.
        consecutiveFailures = 0;

    } catch (error) {
        consecutiveFailures++;

        if (error.name !== "AbortError") {
            console.warn("Traffic update failed:", error.message);
        }

        setConnectionStatus(false);

    } finally {
        if (timeoutId !== null) {
            clearTimeout(timeoutId);
        }

        trafficRequestInProgress = false;

        if (!document.hidden) {
            let delay;

            if (consecutiveFailures > 0) {
                // Retry progressively less often during an outage.
                delay = Math.min(
                    POLL_INTERVAL_MS *
                        (2 ** Math.min(consecutiveFailures - 1, 4)),
                    MAX_RETRY_INTERVAL_MS
                );
            } else {
                // Slight jitter helps spread requests from many viewers.
                delay = POLL_INTERVAL_MS +
                    Math.random() * POLL_JITTER_MS;
            }

            scheduleNextPoll(delay);
        }
    }
}

// Stop polling while the dashboard is hidden.
// Refresh immediately when the customer returns.
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        clearTimeout(pollTimer);
        pollTimer = null;
    } else {
        clearTimeout(pollTimer);
        updateTraffic();
    }
});

// Start the dashboard with a small random delay.
scheduleNextPoll(Math.random() * POLL_JITTER_MS);

