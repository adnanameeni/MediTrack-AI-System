(function () {
    "use strict";
  
    var TOKEN_KEY = "meditrack_token";
    var TYPE_LABELS = {
      fasting: "Fasting",
      before_meal: "Before meal",
      after_meal: "After meal"
    };
  
    var messageBox = document.getElementById("message");
  
    function goToLogin() {
      sessionStorage.removeItem(TOKEN_KEY);
      window.location.replace("/");
    }
  
    var token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) {
      goToLogin();
      return;
    }
  
    document.getElementById("logout-button").addEventListener("click", goToLogin);
  
    // Sends a request with the login token. Returns null if the login expired.
    async function api(method, url, body) {
      var options = { method: method, headers: { Authorization: "Bearer " + token } };
      if (body !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
      var response = await fetch(url, options);
      if (response.status === 401) {
        goToLogin();
        return null;
      }
      var data = null;
      if (response.status !== 204) {
        try {
          data = await response.json();
        } catch (error) {
          data = null;
        }
      }
      return { status: response.status, data: data };
    }
  
    function pad(number) {
      return String(number).padStart(2, "0");
    }
  
    function toLocalInput(iso) {
      var d = new Date(iso);
      return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
        "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
    }
  
    function makeCell(text) {
      var cell = document.createElement("td");
      cell.textContent = text;
      return cell;
    }
  
    function makeButton(label, className, onClick) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = className;
      button.textContent = label;
      button.addEventListener("click", onClick);
      return button;
    }
  
    // ---------------------------------------------------------------
    // Statistics range and statistics boxes
    // ---------------------------------------------------------------
    var presetField = document.getElementById("range-preset");
    var fromField = document.getElementById("range-from");
    var toField = document.getElementById("range-to");
    var rangeMessage = document.getElementById("range-message");
    var glucoseStatsBox = document.getElementById("glucose-stats");
    var bpStatsBox = document.getElementById("bp-stats");
  
    function showRangeMessage(text) {
      rangeMessage.textContent = text;
      rangeMessage.className = "alert alert-warning mt-2 mb-0";
    }
  
    function clearRangeMessage() {
      rangeMessage.textContent = "";
      rangeMessage.className = "alert d-none mt-2 mb-0";
    }
  
    function startOfDay(date) {
      return new Date(date.getFullYear(), date.getMonth(), date.getDate());
    }
  
    // Returns {start, end} as Date objects, or null if the custom dates are invalid.
    function currentRange() {
      var preset = presetField.value;
      var tomorrow = startOfDay(new Date());
      tomorrow.setDate(tomorrow.getDate() + 1);
  
      if (preset === "today") {
        return { start: startOfDay(new Date()), end: tomorrow };
      }
      if (preset === "7" || preset === "30") {
        var start = new Date(tomorrow);
        start.setDate(start.getDate() - Number(preset));
        return { start: start, end: tomorrow };
      }
  
      if (!fromField.value || !toField.value) {
        showRangeMessage("Please choose both a From and a To date.");
        return null;
      }
      var parts = fromField.value.split("-").map(Number);
      var toParts = toField.value.split("-").map(Number);
      var customStart = new Date(parts[0], parts[1] - 1, parts[2]);
      var customEnd = new Date(toParts[0], toParts[1] - 1, toParts[2] + 1);
      if (customEnd <= customStart) {
        showRangeMessage("The To date must not be before the From date.");
        return null;
      }
      if ((customEnd - customStart) / 86400000 > 366) {
        showRangeMessage("Please choose a range of 366 days or less.");
        return null;
      }
      return { start: customStart, end: customEnd };
    }
  
    function showStatsText(box, text) {
      box.textContent = text;
    }
  
    function fmt(value) {
      return value === null || value === undefined ? "-" : String(parseFloat(value));
    }
  
    async function loadStats() {
      clearRangeMessage();
      var range = currentRange();
      if (!range) { return; }
      var query = "?start=" + encodeURIComponent(range.start.toISOString()) +
        "&end=" + encodeURIComponent(range.end.toISOString());
  
      try {
        var glucose = await api("GET", "/stats/glucose" + query);
        if (!glucose) { return; }
        if (glucose.status !== 200) { throw new Error("Unexpected status"); }
        var g = glucose.data;
        showStatsText(glucoseStatsBox, g.count === 0
          ? "No glucose readings in this period."
          : "Readings: " + g.count + " | Average: " + fmt(g.average) +
            " | Lowest: " + fmt(g.minimum) + " | Highest: " + fmt(g.maximum));
  
        var pressure = await api("GET", "/stats/blood-pressure" + query);
        if (!pressure) { return; }
        if (pressure.status !== 200) { throw new Error("Unexpected status"); }
        var p = pressure.data;
        showStatsText(bpStatsBox, p.count === 0
          ? "No blood pressure readings in this period."
          : "Readings: " + p.count +
            " | Average: " + fmt(p.average_systolic) + "/" + fmt(p.average_diastolic) +
            " | Systolic range: " + fmt(p.minimum_systolic) + "-" + fmt(p.maximum_systolic) +
            " | Diastolic range: " + fmt(p.minimum_diastolic) + "-" + fmt(p.maximum_diastolic) +
            " | Average pulse: " + fmt(p.average_pulse));
      } catch (error) {
        showRangeMessage("Could not load statistics. Please try again.");
      }
    }
  
    presetField.addEventListener("change", function () {
      var custom = presetField.value === "custom";
      document.getElementById("custom-from-wrap").classList.toggle("d-none", !custom);
      document.getElementById("custom-to-wrap").classList.toggle("d-none", !custom);
      document.getElementById("custom-apply-wrap").classList.toggle("d-none", !custom);
      if (!custom) { loadStats(); }
    });
    document.getElementById("range-apply").addEventListener("click", loadStats);
  
    // ---------------------------------------------------------------
    // Blood glucose
    // ---------------------------------------------------------------
    var glucoseMessage = document.getElementById("glucose-message");
    var form = document.getElementById("glucose-form");
    var idField = document.getElementById("glucose-id");
    var valueField = document.getElementById("glucose-value");
    var typeField = document.getElementById("glucose-type");
    var timeField = document.getElementById("glucose-time");
    var notesField = document.getElementById("glucose-notes");
    var submitButton = document.getElementById("glucose-submit");
    var cancelButton = document.getElementById("glucose-cancel");
    var rowsBody = document.getElementById("glucose-rows");
    var emptyText = document.getElementById("glucose-empty");
  
    function showGlucoseMessage(text, kind) {
      glucoseMessage.textContent = text;
      glucoseMessage.className = "alert alert-" + kind;
    }
  
    function clearGlucoseMessage() {
      glucoseMessage.textContent = "";
      glucoseMessage.className = "alert d-none";
    }
  
    function resetForm() {
      form.reset();
      idField.value = "";
      submitButton.textContent = "Add reading";
      cancelButton.classList.add("d-none");
    }
  
    function startEdit(reading) {
      clearGlucoseMessage();
      idField.value = String(reading.id);
      valueField.value = reading.glucose_value;
      typeField.value = reading.reading_type;
      timeField.value = toLocalInput(reading.recorded_at);
      notesField.value = reading.notes || "";
      submitButton.textContent = "Save changes";
      cancelButton.classList.remove("d-none");
      valueField.focus();
    }
  
    function renderRows(readings) {
      rowsBody.textContent = "";
      emptyText.classList.toggle("d-none", readings.length > 0);
  
      readings.forEach(function (reading) {
        var row = document.createElement("tr");
        row.appendChild(makeCell(new Date(reading.recorded_at).toLocaleString()));
        row.appendChild(makeCell(String(parseFloat(reading.glucose_value))));
        row.appendChild(makeCell(TYPE_LABELS[reading.reading_type] || reading.reading_type));
        row.appendChild(makeCell(reading.notes || ""));
  
        var actions = document.createElement("td");
        actions.className = "text-end text-nowrap";
        actions.appendChild(makeButton("Edit", "btn btn-outline-primary btn-sm me-1", function () {
          startEdit(reading);
        }));
        actions.appendChild(makeButton("Delete", "btn btn-outline-danger btn-sm", function () {
          removeReading(reading.id);
        }));
        row.appendChild(actions);
        rowsBody.appendChild(row);
      });
    }
  
    async function loadReadings() {
      try {
        var result = await api("GET", "/glucose?limit=50");
        if (!result) { return; }
        if (result.status !== 200) { throw new Error("Unexpected status"); }
        renderRows(result.data);
      } catch (error) {
        showGlucoseMessage("Could not load your readings. Please try again.", "danger");
      }
    }
  
    async function removeReading(id) {
      if (!window.confirm("Delete this reading?")) { return; }
      clearGlucoseMessage();
      try {
        var result = await api("DELETE", "/glucose/" + id);
        if (!result) { return; }
        if (result.status !== 204) { throw new Error("Unexpected status"); }
        if (idField.value === String(id)) { resetForm(); }
        await loadReadings();
        await loadStats();
      } catch (error) {
        showGlucoseMessage("Could not delete the reading. Please try again.", "danger");
      }
    }
  
    cancelButton.addEventListener("click", function () {
      clearGlucoseMessage();
      resetForm();
    });
  
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      clearGlucoseMessage();
  
      if (valueField.value.trim() === "") {
        showGlucoseMessage("Please enter a glucose value.", "warning");
        return;
      }
  
      var body = {
        glucose_value: Number(valueField.value),
        reading_type: typeField.value,
        notes: notesField.value.trim() || null
      };
      if (timeField.value) {
        body.recorded_at = new Date(timeField.value).toISOString();
      }
  
      var editingId = idField.value;
      try {
        var result = editingId
          ? await api("PATCH", "/glucose/" + editingId, body)
          : await api("POST", "/glucose", body);
        if (!result) { return; }
  
        if (result.status === 200 || result.status === 201) {
          resetForm();
          showGlucoseMessage(editingId ? "Reading updated." : "Reading added.", "success");
          await loadReadings();
          await loadStats();
        } else if (result.status === 404) {
          resetForm();
          showGlucoseMessage("That reading no longer exists.", "warning");
          await loadReadings();
          await loadStats();
        } else if (result.status === 422) {
          showGlucoseMessage(
            "Please check the values. Glucose must be above 0 with at most 2 decimals, and the time cannot be in the future.",
            "danger"
          );
        } else {
          showGlucoseMessage("Something went wrong. Please try again.", "danger");
        }
      } catch (error) {
        showGlucoseMessage("Could not reach the server. Is it running?", "danger");
      }
    });
  
    // ---------------------------------------------------------------
    // Blood pressure
    // ---------------------------------------------------------------
    var bpMessage = document.getElementById("bp-message");
    var bpForm = document.getElementById("bp-form");
    var bpIdField = document.getElementById("bp-id");
    var bpSystolicField = document.getElementById("bp-systolic");
    var bpDiastolicField = document.getElementById("bp-diastolic");
    var bpPulseField = document.getElementById("bp-pulse");
    var bpTimeField = document.getElementById("bp-time");
    var bpNotesField = document.getElementById("bp-notes");
    var bpSubmitButton = document.getElementById("bp-submit");
    var bpCancelButton = document.getElementById("bp-cancel");
    var bpRowsBody = document.getElementById("bp-rows");
    var bpEmptyText = document.getElementById("bp-empty");
  
    function showBpMessage(text, kind) {
      bpMessage.textContent = text;
      bpMessage.className = "alert alert-" + kind;
    }
  
    function clearBpMessage() {
      bpMessage.textContent = "";
      bpMessage.className = "alert d-none";
    }
  
    function resetBpForm() {
      bpForm.reset();
      bpIdField.value = "";
      bpSubmitButton.textContent = "Add reading";
      bpCancelButton.classList.add("d-none");
    }
  
    function startBpEdit(reading) {
      clearBpMessage();
      bpIdField.value = String(reading.id);
      bpSystolicField.value = reading.systolic;
      bpDiastolicField.value = reading.diastolic;
      bpPulseField.value = reading.pulse === null ? "" : reading.pulse;
      bpTimeField.value = toLocalInput(reading.recorded_at);
      bpNotesField.value = reading.notes || "";
      bpSubmitButton.textContent = "Save changes";
      bpCancelButton.classList.remove("d-none");
      bpSystolicField.focus();
    }
  
    function renderBpRows(readings) {
      bpRowsBody.textContent = "";
      bpEmptyText.classList.toggle("d-none", readings.length > 0);
  
      readings.forEach(function (reading) {
        var row = document.createElement("tr");
        row.appendChild(makeCell(new Date(reading.recorded_at).toLocaleString()));
        row.appendChild(makeCell(String(reading.systolic)));
        row.appendChild(makeCell(String(reading.diastolic)));
        row.appendChild(makeCell(reading.pulse === null ? "" : String(reading.pulse)));
        row.appendChild(makeCell(reading.notes || ""));
  
        var actions = document.createElement("td");
        actions.className = "text-end text-nowrap";
        actions.appendChild(makeButton("Edit", "btn btn-outline-primary btn-sm me-1", function () {
          startBpEdit(reading);
        }));
        actions.appendChild(makeButton("Delete", "btn btn-outline-danger btn-sm", function () {
          removeBpReading(reading.id);
        }));
        row.appendChild(actions);
        bpRowsBody.appendChild(row);
      });
    }
  
    async function loadBpReadings() {
      try {
        var result = await api("GET", "/blood-pressure?limit=50");
        if (!result) { return; }
        if (result.status !== 200) { throw new Error("Unexpected status"); }
        renderBpRows(result.data);
      } catch (error) {
        showBpMessage("Could not load your readings. Please try again.", "danger");
      }
    }
  
    async function removeBpReading(id) {
      if (!window.confirm("Delete this reading?")) { return; }
      clearBpMessage();
      try {
        var result = await api("DELETE", "/blood-pressure/" + id);
        if (!result) { return; }
        if (result.status !== 204) { throw new Error("Unexpected status"); }
        if (bpIdField.value === String(id)) { resetBpForm(); }
        await loadBpReadings();
        await loadStats();
      } catch (error) {
        showBpMessage("Could not delete the reading. Please try again.", "danger");
      }
    }
  
    bpCancelButton.addEventListener("click", function () {
      clearBpMessage();
      resetBpForm();
    });
  
    bpForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      clearBpMessage();
  
      if (bpSystolicField.value.trim() === "" || bpDiastolicField.value.trim() === "") {
        showBpMessage("Please enter both systolic and diastolic values.", "warning");
        return;
      }
  
      var body = {
        systolic: Number(bpSystolicField.value),
        diastolic: Number(bpDiastolicField.value),
        pulse: bpPulseField.value.trim() === "" ? null : Number(bpPulseField.value),
        notes: bpNotesField.value.trim() || null
      };
      if (bpTimeField.value) {
        body.recorded_at = new Date(bpTimeField.value).toISOString();
      }
  
      var editingId = bpIdField.value;
      try {
        var result = editingId
          ? await api("PATCH", "/blood-pressure/" + editingId, body)
          : await api("POST", "/blood-pressure", body);
        if (!result) { return; }
  
        if (result.status === 200 || result.status === 201) {
          resetBpForm();
          showBpMessage(editingId ? "Reading updated." : "Reading added.", "success");
          await loadBpReadings();
          await loadStats();
        } else if (result.status === 404) {
          resetBpForm();
          showBpMessage("That reading no longer exists.", "warning");
          await loadBpReadings();
          await loadStats();
        } else if (result.status === 422) {
          showBpMessage(
            "Please check the values. Systolic and diastolic must be whole numbers, systolic must be higher than diastolic, and the time cannot be in the future.",
            "danger"
          );
        } else {
          showBpMessage("Something went wrong. Please try again.", "danger");
        }
      } catch (error) {
        showBpMessage("Could not reach the server. Is it running?", "danger");
      }
    });
  
    // ---------------------------------------------------------------
    // Account details
    // ---------------------------------------------------------------
    async function loadUser() {
      try {
        var result = await api("GET", "/auth/me");
        if (!result) { return; }
        if (result.status !== 200) { throw new Error("Unexpected status"); }
        document.getElementById("user-name").textContent = result.data.full_name;
        document.getElementById("user-email").textContent = result.data.email;
      } catch (error) {
        messageBox.textContent = "Could not load your account. Please try again.";
        messageBox.classList.remove("d-none");
      }
    }
  
    loadUser();
    loadReadings();
    loadBpReadings();
    loadStats();
  })();