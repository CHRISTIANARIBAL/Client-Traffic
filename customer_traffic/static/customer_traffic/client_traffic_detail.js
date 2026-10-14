const historyUrl = document.body.dataset.historyUrl;
const rangeSelect = document.getElementById("range");
const statusText = document.getElementById("status");
const uploadValue = document.getElementById("upload");
const downloadValue = document.getElementById("download");

function formatRate(value) {
    value = Number(value) || 0;
    if (value >= 1e9) return (value / 1e9).toFixed(2) + " G";
    if (value >= 1e6) return (value / 1e6).toFixed(2) + " M";
    if (value >= 1e3) return (value / 1e3).toFixed(2) + " k";
    return value.toFixed(0);
}


function getRangeMilliseconds(range) {
    const durations = {
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "2h": 2 * 60 * 60 * 1000,
        "3h": 3 * 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "5h": 5 * 60 * 60 * 1000,
        "6h": 6 * 60 * 60 * 1000,
        "12h": 12 * 60 * 60 * 1000,
        "24h": 24 * 60 * 60 * 1000,
        "7d": 7 * 24 * 60 * 60 * 1000,
        "15d": 15 * 24 * 60 * 60 * 1000,
        "30d": 30 * 24 * 60 * 60 * 1000
    };

    return durations[range] || durations["30m"];
}

const chart = new Chart(document.getElementById("trafficChart"), {
    type: "line",
    data: {
        labels: [],
        
        datasets: [
            {
                label: "Upload",
                data: [],
                parsing: false,
                borderColor: "#10b981",
                backgroundColor: "rgba(16,185,129,0.12)",
                borderWidth: 1.5,
                pointRadius: 0,
                fill: true,
                tension: 0
            },
            {
                label: "Download",
                data: [],
                parsing: false,
                borderColor: "#3b82f6",
                backgroundColor: "rgba(59,130,246,0.10)",
                borderWidth: 1.5,
                pointRadius: 0,
                fill: true,
                tension: 0
            }
        ]

    },
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
            legend: { display: false },
            tooltip: {
                callbacks: {
                    label: context => context.dataset.label + ": " +
                        formatRate(context.parsed.y) + "bps"
                }
            }
        },
        scales: {
            
            x: {
                type: "time",
                min: Date.now() - getRangeMilliseconds(rangeSelect.value),
                max: Date.now(),
                time: {
                    tooltipFormat: "MMM d, yyyy HH:mm:ss",
                    displayFormats: {
                        minute: "HH:mm",
                        hour: "MMM d HH:mm",
                        day: "MMM d"
                    }
                },
                ticks: {
                    color: "#94a3b8",
                    maxTicksLimit: 8
                },
                grid: {
                    color: "rgba(148,163,184,0.08)"
                }
            },

            y: {
                beginAtZero: true,
                ticks: {
                    color: "#94a3b8",
                    callback: value => formatRate(value) + "bps"
                },
                grid: { color: "rgba(148,163,184,0.10)" }
            }
        }
    }
});

let loading = false;
let requestId = 0;


let activeRange = null;
let lastTimestamp = null;

function formatTimestamp(timestamp, selectedRange) {
    const date = new Date(timestamp);

    if (Number.isNaN(date.getTime())) {
        return "Unknown time";
    }

    return date.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: selectedRange === "30m" ? "2-digit" : undefined
    });
}


async function loadTraffic() {
    const currentRequestId = ++requestId;
    const selectedRange = rangeSelect.value;

    try {
        const response = await fetch(
            `${historyUrl}?range=${encodeURIComponent(selectedRange)}&_=${Date.now()}`,
            { cache: "no-store" }
        );

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Unable to load traffic");
        }

        if (currentRequestId !== requestId) return;

        const points = data.history || [];
        const current = data.current ||
            (points.length ? points[points.length - 1] : null);

        uploadValue.textContent = current
            ? formatRate(current.upload)
            : "--";

        downloadValue.textContent = current
            ? formatRate(current.download)
            : "--";

        // Reset the graph only when the selected range changes.
        if (activeRange !== selectedRange) {
            activeRange = selectedRange;
            lastTimestamp = null;

            chart.data.datasets[0].data = points.map(item => ({
                x: new Date(item.timestamp).getTime(),
                y: Number(item.upload)
            }));

            chart.data.datasets[1].data = points.map(item => ({
                x: new Date(item.timestamp).getTime(),
                y: Number(item.download)
            }));

            lastTimestamp = points.length
                ? points[points.length - 1].timestamp
                : null;

        } else if (points.length) {
            // Append only records newer than the last plotted record.
            for (const item of points) {
                if (
                    lastTimestamp &&
                    item.timestamp <= lastTimestamp
                ) {
                    continue;
                }

                const timestamp = new Date(item.timestamp).getTime();

                if (Number.isNaN(timestamp)) continue;

                chart.data.datasets[0].data.push({
                    x: timestamp,
                    y: Number(item.upload)
                });

                chart.data.datasets[1].data.push({
                    x: timestamp,
                    y: Number(item.download)
                });

                lastTimestamp = item.timestamp;
            }
        }

        // Keep the selected time window fixed relative to now.
        const now = Date.now();

        chart.options.scales.x.min =
            now - getRangeMilliseconds(selectedRange);

        chart.options.scales.x.max = now;

        // Remove points outside the visible time window.
        const cutoff = chart.options.scales.x.min;

        for (const dataset of chart.data.datasets) {
            dataset.data = dataset.data.filter(
                point => point.x >= cutoff
            );
        }

        chart.update("none");

        statusText.textContent =
            `${chart.data.datasets[0].data.length} plotted samples · ` +
            `${rangeSelect.options[rangeSelect.selectedIndex].text} · ` +
            `Refreshed ${new Date().toLocaleTimeString()}`;

    } catch (error) {
        if (currentRequestId === requestId) {
            statusText.textContent = "Error: " + error.message;
            console.error("Traffic graph error:", error);
        }
    }
}

rangeSelect.addEventListener("change", loadTraffic);

loadTraffic();
setInterval(loadTraffic, 5000);