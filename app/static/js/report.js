(function () {
    "use strict";
  
    var dashboard = window.MediTrackDashboard;
    var anchor = document.getElementById("range-message");
    if (!dashboard || !anchor) { return; }
  
    var wrap = document.createElement("div");
    wrap.className = "mt-2";
  
    var button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-outline-secondary btn-sm";
    button.textContent = "Download PDF report";
  
    var status = document.createElement("div");
    status.className = "small mt-1 d-none";
  
    wrap.appendChild(button);
    wrap.appendChild(status);
    anchor.insertAdjacentElement("afterend", wrap);
  
    function pad(number) {
      return String(number).padStart(2, "0");
    }
  
    function showStatus(text, isError) {
      status.textContent = text;
      status.className = "small mt-1 " + (isError ? "text-danger" : "text-muted");
    }
  
    function clearStatus() {
      status.textContent = "";
      status.className = "small mt-1 d-none";
    }
  
    button.addEventListener("click", async function () {
      clearStatus();
      var range = dashboard.getRange();
      if (!range) { return; }
  
      // Minutes east of UTC at the start of the chosen range (for example 300 for UTC+05:00).
      var offset = -range.start.getTimezoneOffset();
      var url = "/reports/pdf?start=" + encodeURIComponent(range.start.toISOString()) +
        "&end=" + encodeURIComponent(range.end.toISOString()) +
        "&offset_minutes=" + offset;
  
      button.disabled = true;
      showStatus("Preparing your report...", false);
      try {
        var response = await dashboard.authorizedFetch(url);
        if (!response) { return; }
        if (!response.ok) {
          showStatus("Could not create the report. Please check the dates and try again.", true);
          return;
        }
        var blob = await response.blob();
        var today = new Date();
        var link = document.createElement("a");
        var objectUrl = URL.createObjectURL(blob);
        link.href = objectUrl;
        link.download = "meditrack-report-" + today.getFullYear() + "-" +
          pad(today.getMonth() + 1) + "-" + pad(today.getDate()) + ".pdf";
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(function () { URL.revokeObjectURL(objectUrl); }, 10000);
        showStatus("Report downloaded.", false);
      } catch (error) {
        showStatus("Could not reach the server. Is it running?", true);
      } finally {
        button.disabled = false;
      }
    });
  })();