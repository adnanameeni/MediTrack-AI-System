(function () {
    "use strict";
  
    // Pinned Chart.js version, loaded only when the dashboard needs it.
    var CHART_JS_URL = "https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.js";
    var TYPE_LABELS = {
      fasting: "Fasting",
      before_meal: "Before meal",
      after_meal: "After meal"
    };
  
    var libraryPromise = null;
    var latestRequest = 0;
    var panels = {};
    var instances = {};
  
    function loadLibrary() {
      if (window.Chart) { return Promise.resolve(); }
      if (!libraryPromise) {
        libraryPromise = new Promise(function (resolve, reject) {
          var script = document.createElement("script");
          script.src = CHART_JS_URL;
          script.async = true;
          script.onload = function () { resolve(); };
          script.onerror = function () {
            libraryPromise = null;
            reject(new Error("Chart.js could not be loaded"));
          };
          document.head.appendChild(script);
        });
      }
      return libraryPromise;
    }
  
    // Creates (once) a chart area right after the statistics box with this id.
    function getPanel(key, anchorId, label) {
      if (panels[key]) { return panels[key]; }
      var anchor = document.getElementById(anchorId);
      if (!anchor) { return null; }
  
      var wrap = document.createElement("div");
      wrap.className = "mt-3";
  
      var note = document.createElement("p");
      note.className = "text-muted small mb-1 d-none";
  
      var holder = document.createElement("div");
      holder.style.position = "relative";
      holder.style.height = "260px";
  
      var canvas = document.createElement("canvas");
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", label);
      holder.appendChild(canvas);
  
      wrap.appendChild(note);
      wrap.appendChild(holder);
      anchor.insertAdjacentElement("afterend", wrap);
  
      panels[key] = { note: note, holder: holder, canvas: canvas };
      return panels[key];
    }
  
    function setNote(panel, text) {
      panel.note.textContent = text;
      panel.note.classList.toggle("d-none", text === "");
    }
  
    function destroy(key) {
      if (instances[key]) {
        instances[key].destroy();
        instances[key] = null;
      }
    }
  
    function tickFormatter(spanMs) {
      var oneDay = 86400000;
      return function (value) {
        var d = new Date(value);
        if (spanMs <= 2 * oneDay) {
          return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        }
        return d.toLocaleDateString([], { month: "short", day: "numeric" });
      };
    }
  
    function baseOptions(range) {
      var min = range.start.getTime();
      var max = range.end.getTime();
      return {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "nearest", intersect: false },
        scales: {
          x: {
            type: "linear",
            min: min,
            max: max,
            ticks: { maxTicksLimit: 8, callback: tickFormatter(max - min) }
          },
          y: { beginAtZero: false }
        },
        plugins: {
          legend: { display: true },
          tooltip: {
            callbacks: {
              title: function (items) {
                return new Date(items[0].parsed.x).toLocaleString();
              }
            }
          }
        }
      };
    }
  
    function lineDataset(label, color, points) {
      return {
        label: label,
        data: points,
        borderColor: color,
        backgroundColor: color,
        borderWidth: 2,
        pointRadius: 3,
        tension: 0.2
      };
    }
  
    function drawGlucose(panel, data, range) {
      destroy("glucose");
      if (data.points.length === 0) {
        panel.holder.classList.add("d-none");
        setNote(panel, "No glucose readings to chart in this period.");
        return;
      }
      panel.holder.classList.remove("d-none");
      setNote(panel, data.truncated ? "Showing the most recent readings in this period." : "");
  
      var points = data.points.map(function (p) {
        return { x: new Date(p.recorded_at).getTime(), y: p.glucose_value, type: p.reading_type };
      });
      var options = baseOptions(range);
      options.plugins.legend.display = false;
      options.plugins.tooltip.callbacks.label = function (item) {
        return "Glucose: " + item.parsed.y;
      };
      options.plugins.tooltip.callbacks.afterLabel = function (item) {
        var type = item.raw.type;
        return TYPE_LABELS[type] || type;
      };
  
      instances.glucose = new window.Chart(panel.canvas, {
        type: "line",
        data: { datasets: [lineDataset("Glucose", "#0d6efd", points)] },
        options: options
      });
    }
  
    function drawPressure(panel, data, range) {
      destroy("pressure");
      if (data.points.length === 0) {
        panel.holder.classList.add("d-none");
        setNote(panel, "No blood pressure readings to chart in this period.");
        return;
      }
      panel.holder.classList.remove("d-none");
      setNote(panel, data.truncated ? "Showing the most recent readings in this period." : "");
  
      var systolic = [];
      var diastolic = [];
      data.points.forEach(function (p) {
        var x = new Date(p.recorded_at).getTime();
        systolic.push({ x: x, y: p.systolic, pulse: p.pulse });
        diastolic.push({ x: x, y: p.diastolic, pulse: p.pulse });
      });
      var options = baseOptions(range);
      options.plugins.tooltip.callbacks.label = function (item) {
        return item.dataset.label + ": " + item.parsed.y;
      };
      options.plugins.tooltip.callbacks.afterLabel = function (item) {
        return item.raw.pulse === null || item.raw.pulse === undefined
          ? ""
          : "Pulse: " + item.raw.pulse;
      };
  
      instances.pressure = new window.Chart(panel.canvas, {
        type: "line",
        data: {
          datasets: [
            lineDataset("Systolic", "#dc3545", systolic),
            lineDataset("Diastolic", "#198754", diastolic)
          ]
        },
        options: options
      });
    }
  
    function showProblem(text) {
      ["glucose", "pressure"].forEach(function (key) {
        var panel = panels[key];
        if (!panel) { return; }
        destroy(key);
        panel.holder.classList.add("d-none");
        setNote(panel, text);
      });
    }
  
    // api: the dashboard's request helper. range: {start, end} Date objects.
    async function update(api, range) {
      var glucosePanel = getPanel("glucose", "glucose-stats", "Glucose readings over time");
      var pressurePanel = getPanel("pressure", "bp-stats", "Blood pressure readings over time");
      if (!glucosePanel || !pressurePanel) { return; }
  
      var requestId = ++latestRequest;
      var query = "?start=" + encodeURIComponent(range.start.toISOString()) +
        "&end=" + encodeURIComponent(range.end.toISOString());
  
      var results;
      var libraryReady;
      try {
        results = await Promise.all([
          api("GET", "/charts/glucose" + query),
          api("GET", "/charts/blood-pressure" + query),
          loadLibrary().then(function () { return true; }, function () { return false; })
        ]);
      } catch (error) {
        if (requestId === latestRequest) { showProblem("Could not load chart data. Please try again."); }
        return;
      }
      if (requestId !== latestRequest) { return; }
  
      var glucose = results[0];
      var pressure = results[1];
      libraryReady = results[2];
      if (!glucose || !pressure) { return; }
  
      if (!libraryReady) {
        showProblem("The chart library could not be loaded. Charts need an internet connection.");
        return;
      }
      if (glucose.status !== 200 || pressure.status !== 200) {
        showProblem("Could not load chart data. Please try again.");
        return;
      }
  
      drawGlucose(glucosePanel, glucose.data, range);
      drawPressure(pressurePanel, pressure.data, range);
    }
  
    window.MediTrackCharts = { update: update };
  })();