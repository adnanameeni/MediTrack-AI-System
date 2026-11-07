(function () {
    "use strict";
  
    var TOKEN_KEY = "meditrack_token";
    var USERS_PAGE_SIZE = 10;
    var AUDIT_PAGE_SIZE = 15;
  
    var ACTION_LABELS = {
      admin_promoted: "Promoted to administrator",
      admin_demoted: "Administrator access removed",
      role_changed: "Role changed (command line)",
      user_activated: "Account activated",
      user_deactivated: "Account deactivated"
    };
  
    var VIEW_TITLES = {
      overview: "Overview",
      users: "Users and roles",
      audit: "Audit log",
      profile: "My profile"
    };
  
    // The private page is only shown after the server confirms the role.
    // The server checks the role again on every /admin/... request.
    var token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) {
      window.location.replace("/");
      return;
    }
  
    var me = null;
    var currentView = "overview";
    var loaded = { overview: false, users: false, audit: false };
    var usersState = { offset: 0, total: 0 };
    var auditState = { offset: 0, total: 0 };
    var openUser = null;
    var searchTimer = null;
    var usersRequest = 0;
    var auditRequest = 0;
  
    function $(id) {
      return document.getElementById(id);
    }
  
    // ---------------------------------------------------------------
    // Small helpers (all text goes in with textContent, so data is never read as HTML)
    // ---------------------------------------------------------------
    function make(tag, className, text) {
      var node = document.createElement(tag);
      if (className) { node.className = className; }
      if (text !== undefined && text !== null) { node.textContent = text; }
      return node;
    }
  
    function clear(node) {
      while (node.firstChild) { node.removeChild(node.firstChild); }
    }
  
    function initials(name) {
      var parts = String(name || "").trim().split(/\s+/).filter(Boolean);
      if (parts.length === 0) { return "?"; }
      var letters = parts[0].charAt(0);
      if (parts.length > 1) { letters += parts[parts.length - 1].charAt(0); }
      return letters.toUpperCase();
    }
  
    function formatNumber(value) {
      return Number(value || 0).toLocaleString();
    }
  
    function formatDateTime(iso) {
      if (!iso) { return "-"; }
      var date = new Date(iso);
      if (isNaN(date.getTime())) { return "-"; }
      return date.toLocaleString(undefined, {
        year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
      });
    }
  
    function formatDate(iso) {
      if (!iso) { return "-"; }
      var date = new Date(iso);
      if (isNaN(date.getTime())) { return "-"; }
      return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    }
  
    function goToLogin() {
      sessionStorage.removeItem(TOKEN_KEY);
      window.location.replace("/");
    }
  
    function goToUserDashboard() {
      window.location.replace("/dashboard");
    }
  
    // Sends a request with the login token.
    // Returns {status, data}, or null when the page is being redirected away.
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
      if (response.status === 403) {
        // Not (or no longer) an administrator.
        goToUserDashboard();
        return null;
      }
      var data = null;
      try {
        data = await response.json();
      } catch (error) {
        data = null;
      }
      return { status: response.status, data: data };
    }
  
    function errorText(result, fallback) {
      if (!result) { return fallback; }
      if (result.status === 404) { return "That user no longer exists."; }
      if (result.status === 409 && result.data && typeof result.data.detail === "string") {
        return result.data.detail;
      }
      if (result.status === 422) { return "That request was not valid."; }
      return fallback;
    }
  
    // ---------------------------------------------------------------
    // Page message (top of the content area)
    // ---------------------------------------------------------------
    var messageBox = $("ad-message");
    var messageTimer = null;
  
    function showMessage(text, kind) {
      clear(messageBox);
      var alert = make("div", "ad-alert ad-alert-" + kind);
      alert.appendChild(make("span", null, text));
      var close = make("button", null, "\u00d7");
      close.type = "button";
      close.setAttribute("aria-label", "Dismiss message");
      close.addEventListener("click", function () { clear(messageBox); });
      alert.appendChild(close);
      messageBox.appendChild(alert);
      window.clearTimeout(messageTimer);
      if (kind === "success") {
        messageTimer = window.setTimeout(function () { clear(messageBox); }, 6000);
      }
    }
  
    // ---------------------------------------------------------------
    // Navigation
    // ---------------------------------------------------------------
    var sidebar = $("ad-sidebar");
    var backdrop = $("ad-backdrop");
    var menuButton = $("ad-menu-button");
  
    function setMenu(open) {
      sidebar.classList.toggle("open", open);
      backdrop.classList.toggle("open", open);
      menuButton.setAttribute("aria-expanded", open ? "true" : "false");
    }
  
    function showView(name) {
      if (!VIEW_TITLES[name]) { name = "overview"; }
      currentView = name;
      Object.keys(VIEW_TITLES).forEach(function (key) {
        $("view-" + key).hidden = key !== name;
      });
      document.querySelectorAll(".ad-nav-link[data-view]").forEach(function (button) {
        var active = button.getAttribute("data-view") === name;
        button.classList.toggle("active", active);
        if (active) {
          button.setAttribute("aria-current", "page");
        } else {
          button.removeAttribute("aria-current");
        }
      });
      $("ad-page-title").textContent = VIEW_TITLES[name];
      document.title = VIEW_TITLES[name] + " | Admin | MediTrack AI";
      setMenu(false);
      clear(messageBox);
  
      if (name === "overview" && !loaded.overview) { loadOverview(); }
      if (name === "users" && !loaded.users) { loadUsers(); }
      if (name === "audit" && !loaded.audit) { loadAudit(); }
      window.scrollTo(0, 0);
    }
  
    document.querySelectorAll(".ad-nav-link[data-view]").forEach(function (button) {
      button.addEventListener("click", function () {
        var name = button.getAttribute("data-view");
        if (window.location.hash !== "#" + name) {
          window.history.replaceState(null, "", "#" + name);
        }
        showView(name);
      });
    });
  
    menuButton.addEventListener("click", function () {
      setMenu(!sidebar.classList.contains("open"));
    });
    backdrop.addEventListener("click", function () { setMenu(false); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { setMenu(false); }
    });
  
    $("ad-logout").addEventListener("click", goToLogin);
    $("profile-logout").addEventListener("click", goToLogin);
  
    // ---------------------------------------------------------------
    // Profile
    // ---------------------------------------------------------------
    function renderProfile() {
      $("ad-name").textContent = me.full_name;
      $("ad-email").textContent = me.email;
      $("ad-avatar").textContent = initials(me.full_name);
      $("ad-welcome-name").textContent = me.full_name;
      $("profile-avatar").textContent = initials(me.full_name);
      $("profile-name").textContent = me.full_name;
      $("profile-email").textContent = me.email;
      $("profile-role").textContent = me.role === "admin" ? "Administrator" : me.role;
      $("profile-status").textContent = me.is_active ? "Active" : "Deactivated";
      $("profile-since").textContent = formatDate(me.created_at);
      $("profile-id").textContent = "#" + me.id;
    }
  
    // ---------------------------------------------------------------
    // Overview
    // ---------------------------------------------------------------
    var trendDays = $("trend-days");
  
    function setText(id, value) {
      $(id).textContent = value;
    }
  
    function drawTrend(trend) {
      var holder = $("trend-chart");
      clear(holder);
      var points = trend.points || [];
      var width = 600;
      var height = 190;
      var left = 28;
      var bottom = 22;
      var top = 10;
      var plotWidth = width - left - 6;
      var plotHeight = height - bottom - top;
      var max = 1;
      points.forEach(function (point) { if (point.count > max) { max = point.count; } });
  
      var ns = "http://www.w3.org/2000/svg";
      var svg = document.createElementNS(ns, "svg");
      svg.setAttribute("viewBox", "0 0 " + width + " " + height);
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute("aria-hidden", "true");
  
      function svgNode(tag, attributes, text) {
        var node = document.createElementNS(ns, tag);
        Object.keys(attributes).forEach(function (key) { node.setAttribute(key, attributes[key]); });
        if (text !== undefined) { node.textContent = text; }
        return node;
      }
  
      [0, 0.5, 1].forEach(function (fraction) {
        var y = top + plotHeight - fraction * plotHeight;
        svg.appendChild(svgNode("line", { x1: left, x2: width - 6, y1: y, y2: y, "class": "grid" }));
        svg.appendChild(svgNode("text", { x: left - 6, y: y + 3, "text-anchor": "end", "class": "axis" },
          String(Math.round(fraction * max))));
      });
  
      var slot = points.length ? plotWidth / points.length : plotWidth;
      var barWidth = Math.max(2, slot * 0.62);
      points.forEach(function (point, index) {
        var barHeight = point.count > 0 ? Math.max(3, (point.count / max) * plotHeight) : 2;
        var title = svgNode("title", {}, point.date + ": " + point.count);
        var bar = svgNode("rect", {
          x: left + index * slot + (slot - barWidth) / 2,
          y: top + plotHeight - barHeight,
          width: barWidth,
          height: barHeight,
          rx: 2,
          "class": point.count > 0 ? "bar" : "bar-zero"
        });
        bar.appendChild(title);
        svg.appendChild(bar);
      });
  
      if (points.length) {
        var last = points.length - 1;
        [[0, "start"], [Math.floor(last / 2), "middle"], [last, "end"]].forEach(function (pair) {
          var index = pair[0];
          var anchor = pair[1];
          var x = left + index * slot + slot / 2;
          if (anchor === "start") { x = left; }
          if (anchor === "end") { x = width - 6; }
          svg.appendChild(svgNode("text", { x: x, y: height - 5, "text-anchor": anchor, "class": "axis" },
            formatDate(points[index].date + "T12:00:00")));
        });
      }
      holder.appendChild(svg);
    }
  
    async function loadOverview() {
      var result;
      try {
        result = await api("GET", "/admin/overview?days=" + encodeURIComponent(trendDays.value));
      } catch (error) {
        showMessage("Could not reach the server. Is it running?", "error");
        return;
      }
      if (!result) { return; }
      if (result.status !== 200 || !result.data) {
        showMessage("The overview could not be loaded.", "error");
        return;
      }
      var data = result.data;
      setText("stat-total", formatNumber(data.users.total));
      setText("stat-admins", formatNumber(data.users.admins));
      setText("stat-normal", formatNumber(data.users.normal_users));
      setText("stat-glucose", formatNumber(data.records.glucose_readings));
      setText("stat-bp", formatNumber(data.records.blood_pressure_readings));
      setText("stat-chats", formatNumber(data.records.conversations));
      setText("fact-active", formatNumber(data.users.active));
      setText("fact-inactive", formatNumber(data.users.inactive));
      setText("fact-active-admins", formatNumber(data.users.active_admins));
      setText("fact-24h", formatNumber(data.recent_registrations.last_24_hours));
      setText("fact-7d", formatNumber(data.recent_registrations.last_7_days));
      setText("fact-30d", formatNumber(data.recent_registrations.last_30_days));
      setText("fact-latest", formatDateTime(data.recent_registrations.latest_registration_at));
      setText("trend-total", formatNumber(data.registration_trend.total));
      drawTrend(data.registration_trend);
      loaded.overview = true;
    }
  
    trendDays.addEventListener("change", function () { loadOverview(); });
  
    // ---------------------------------------------------------------
    // Users
    // ---------------------------------------------------------------
    var usersBody = $("users-body");
  
    function roleChip(role) {
      return make("span", "ad-chip " + (role === "admin" ? "chip-admin" : "chip-user"),
        role === "admin" ? "Administrator" : "User");
    }
  
    function statusChip(active) {
      return make("span", "ad-chip " + (active ? "chip-active" : "chip-inactive"),
        active ? "Active" : "Deactivated");
    }
  
    function renderUserRow(user) {
      var row = document.createElement("tr");
  
      var personCell = document.createElement("td");
      var person = make("div", "ad-cell-person");
      var nameLine = make("strong", null, user.full_name);
      if (me && user.id === me.id) { nameLine.appendChild(make("span", "ad-you", "You")); }
      person.appendChild(nameLine);
      person.appendChild(make("span", null, user.email));
      personCell.appendChild(person);
      row.appendChild(personCell);
  
      var roleCell = document.createElement("td");
      roleCell.appendChild(roleChip(user.role));
      row.appendChild(roleCell);
  
      var statusCell = document.createElement("td");
      statusCell.appendChild(statusChip(user.is_active));
      row.appendChild(statusCell);
  
      row.appendChild(make("td", "ad-muted", formatDate(user.created_at)));
  
      var actionCell = make("td", "ad-td-action");
      var button = make("button", "ad-row-button", "View");
      button.type = "button";
      button.setAttribute("aria-label", "View " + user.full_name);
      button.addEventListener("click", function () { openUserDialog(user.id); });
      actionCell.appendChild(button);
      row.appendChild(actionCell);
      return row;
    }
  
    async function loadUsers() {
      var requestId = ++usersRequest;
      var query = "limit=" + USERS_PAGE_SIZE + "&offset=" + usersState.offset;
      var search = $("user-search").value.trim();
      var role = $("user-role").value;
      if (search) { query += "&search=" + encodeURIComponent(search); }
      if (role) { query += "&role=" + encodeURIComponent(role); }
  
      var result;
      try {
        result = await api("GET", "/admin/users?" + query);
      } catch (error) {
        showMessage("Could not reach the server. Is it running?", "error");
        return;
      }
      if (!result || requestId !== usersRequest) { return; }
      if (result.status !== 200 || !result.data) {
        showMessage("The user list could not be loaded.", "error");
        return;
      }
      var page = result.data;
      // A page past the end (for example after a filter change) goes back to the first page.
      if (page.items.length === 0 && page.total > 0 && usersState.offset > 0) {
        usersState.offset = 0;
        loadUsers();
        return;
      }
      usersState.total = page.total;
      clear(usersBody);
      page.items.forEach(function (user) { usersBody.appendChild(renderUserRow(user)); });
      $("users-empty").hidden = page.items.length !== 0;
      var from = page.total === 0 ? 0 : page.offset + 1;
      var to = page.offset + page.items.length;
      $("users-summary").textContent = "Showing " + from + "-" + to + " of " + formatNumber(page.total);
      $("users-prev").disabled = page.offset === 0;
      $("users-next").disabled = page.offset + page.items.length >= page.total;
      loaded.users = true;
    }
  
    function reloadUsersFromStart() {
      usersState.offset = 0;
      loadUsers();
    }
  
    $("user-search").addEventListener("input", function () {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(reloadUsersFromStart, 300);
    });
    $("user-role").addEventListener("change", reloadUsersFromStart);
    $("users-refresh").addEventListener("click", function () { loadUsers(); });
    $("users-prev").addEventListener("click", function () {
      usersState.offset = Math.max(0, usersState.offset - USERS_PAGE_SIZE);
      loadUsers();
    });
    $("users-next").addEventListener("click", function () {
      usersState.offset += USERS_PAGE_SIZE;
      loadUsers();
    });
  
    // ---------------------------------------------------------------
    // User dialog and confirmations
    // ---------------------------------------------------------------
    var userDialog = $("user-dialog");
    var confirmDialog = $("confirm-dialog");
    var dialogMessage = $("dialog-message");
    var roleButton = $("dialog-role-button");
    var statusButton = $("dialog-status-button");
  
    function showDialogMessage(text) {
      dialogMessage.textContent = text || "";
    }
  
    function setDialogBusy(busy) {
      roleButton.disabled = busy || roleButton.dataset.locked === "1";
      statusButton.disabled = busy || statusButton.dataset.locked === "1";
    }
  
    function renderUserDialog(user) {
      openUser = user;
      var isSelf = me && user.id === me.id;
      $("dialog-avatar").textContent = initials(user.full_name);
      $("dialog-name").textContent = user.full_name;
      $("dialog-email").textContent = user.email;
  
      var role = $("dialog-role");
      role.className = "ad-chip " + (user.role === "admin" ? "chip-admin" : "chip-user");
      role.textContent = user.role === "admin" ? "Administrator" : "User";
      var status = $("dialog-status");
      status.className = "ad-chip " + (user.is_active ? "chip-active" : "chip-inactive");
      status.textContent = user.is_active ? "Active" : "Deactivated";
  
      $("dialog-joined").textContent = formatDate(user.created_at);
      $("dialog-glucose").textContent = formatNumber(user.glucose_reading_count);
      $("dialog-bp").textContent = formatNumber(user.blood_pressure_reading_count);
      $("dialog-chats").textContent = formatNumber(user.conversation_count);
  
      roleButton.textContent = user.role === "admin" ? "Remove administrator access" : "Make administrator";
      statusButton.textContent = user.is_active ? "Deactivate account" : "Reactivate account";
      statusButton.className = user.is_active ? "btn btn-outline-danger" : "btn btn-outline-primary";
  
      // You cannot take away your own access. The server enforces this too.
      var roleLocked = isSelf && user.role === "admin";
      var statusLocked = isSelf && user.is_active;
      roleButton.dataset.locked = roleLocked ? "1" : "0";
      statusButton.dataset.locked = statusLocked ? "1" : "0";
      roleButton.title = roleLocked ? "You cannot remove your own administrator access" : "";
      statusButton.title = statusLocked ? "You cannot deactivate your own account" : "";
      setDialogBusy(false);
      showDialogMessage(isSelf ? "This is your own account, so your own access cannot be removed or deactivated here." : "");
      dialogMessage.style.background = isSelf ? "var(--mt-primary-soft)" : "";
      dialogMessage.style.color = isSelf ? "var(--mt-primary-dark)" : "";
    }
  
    async function openUserDialog(userId) {
      var result;
      try {
        result = await api("GET", "/admin/users/" + encodeURIComponent(userId));
      } catch (error) {
        showMessage("Could not reach the server. Is it running?", "error");
        return;
      }
      if (!result) { return; }
      if (result.status !== 200 || !result.data) {
        showMessage(errorText(result, "The user could not be loaded."), "error");
        if (result.status === 404) { loadUsers(); }
        return;
      }
      renderUserDialog(result.data);
      if (!userDialog.open) { userDialog.showModal(); }
    }
  
    $("dialog-close").addEventListener("click", function () { userDialog.close(); });
    userDialog.addEventListener("click", function (event) {
      if (event.target === userDialog) { userDialog.close(); }
    });
  
    // Asks the person to confirm. Resolves to true or false.
    function confirmAction(title, text, okLabel, danger) {
      return new Promise(function (resolve) {
        $("confirm-title").textContent = title;
        $("confirm-text").textContent = text;
        var ok = $("confirm-ok");
        ok.textContent = okLabel;
        ok.className = danger ? "btn btn-danger" : "btn btn-primary";
        var answer = false;
  
        function finish(value) {
          answer = value;
          confirmDialog.close();
        }
        function onOk() { finish(true); }
        function onCancel() { finish(false); }
        function onClose() {
          ok.removeEventListener("click", onOk);
          $("confirm-cancel").removeEventListener("click", onCancel);
          confirmDialog.removeEventListener("close", onClose);
          resolve(answer);
        }
        ok.addEventListener("click", onOk);
        $("confirm-cancel").addEventListener("click", onCancel);
        confirmDialog.addEventListener("close", onClose);
        confirmDialog.showModal();
      });
    }
  
    function markDataStale() {
      loaded.overview = false;
      loaded.audit = false;
    }
  
    async function applyChange(path, body, successText) {
      setDialogBusy(true);
      showDialogMessage("");
      dialogMessage.style.background = "";
      dialogMessage.style.color = "";
      var result;
      try {
        result = await api("PATCH", path, body);
      } catch (error) {
        showDialogMessage("Could not reach the server. Is it running?");
        setDialogBusy(false);
        return;
      }
      if (!result) { return; }
      if (result.status === 200 && result.data) {
        renderUserDialog(result.data);
        markDataStale();
        showMessage(successText, "success");
        loadUsers();
        return;
      }
      showDialogMessage(errorText(result, "The change could not be saved. Please try again."));
      setDialogBusy(false);
      if (result.status === 404) { loadUsers(); }
    }
  
    roleButton.addEventListener("click", async function () {
      if (!openUser || roleButton.dataset.locked === "1") { return; }
      var user = openUser;
      var promote = user.role !== "admin";
      var confirmed = await confirmAction(
        promote ? "Make administrator?" : "Remove administrator access?",
        promote
          ? user.full_name + " will be able to open this administration area and manage other users."
          : user.full_name + " will lose access to this administration area and become a normal user.",
        promote ? "Make administrator" : "Remove access",
        !promote
      );
      if (!confirmed) { return; }
      applyChange(
        "/admin/users/" + encodeURIComponent(user.id) + "/role",
        { role: promote ? "admin" : "user" },
        user.full_name + (promote ? " is now an administrator." : " is now a normal user.")
      );
    });
  
    statusButton.addEventListener("click", async function () {
      if (!openUser || statusButton.dataset.locked === "1") { return; }
      var user = openUser;
      var activate = !user.is_active;
      var confirmed = await confirmAction(
        activate ? "Reactivate account?" : "Deactivate account?",
        activate
          ? user.full_name + " will be able to log in again."
          : user.full_name + " will be signed out and will not be able to log in until reactivated.",
        activate ? "Reactivate" : "Deactivate",
        !activate
      );
      if (!confirmed) { return; }
      applyChange(
        "/admin/users/" + encodeURIComponent(user.id) + "/status",
        { is_active: activate },
        user.full_name + (activate ? "'s account was reactivated." : "'s account was deactivated.")
      );
    });
  
    // ---------------------------------------------------------------
    // Audit log
    // ---------------------------------------------------------------
    var auditBody = $("audit-body");
  
    function personCell(person, emptyText) {
      var cell = document.createElement("td");
      if (!person) {
        cell.appendChild(make("span", "ad-muted", emptyText));
        return cell;
      }
      var wrap = make("div", "ad-cell-person");
      wrap.appendChild(make("strong", null, person.full_name));
      wrap.appendChild(make("span", null, person.email));
      cell.appendChild(wrap);
      return cell;
    }
  
    function renderAuditRow(entry) {
      var row = document.createElement("tr");
      row.appendChild(make("td", "ad-muted", formatDateTime(entry.created_at)));
      var actionCell = document.createElement("td");
      actionCell.appendChild(make("span", "ad-chip chip-action", ACTION_LABELS[entry.action] || entry.action));
      row.appendChild(actionCell);
      row.appendChild(personCell(entry.admin, "Command line"));
      row.appendChild(personCell(entry.target, "Deleted account"));
      row.appendChild(make("td", "ad-muted", entry.detail || "-"));
      return row;
    }
  
    async function loadAudit() {
      var requestId = ++auditRequest;
      var query = "limit=" + AUDIT_PAGE_SIZE + "&offset=" + auditState.offset;
      var action = $("audit-action").value;
      if (action) { query += "&action=" + encodeURIComponent(action); }
  
      var result;
      try {
        result = await api("GET", "/admin/activity?" + query);
      } catch (error) {
        showMessage("Could not reach the server. Is it running?", "error");
        return;
      }
      if (!result || requestId !== auditRequest) { return; }
      if (result.status !== 200 || !result.data) {
        showMessage("The audit log could not be loaded.", "error");
        return;
      }
      var page = result.data;
      if (page.items.length === 0 && page.total > 0 && auditState.offset > 0) {
        auditState.offset = 0;
        loadAudit();
        return;
      }
      auditState.total = page.total;
      clear(auditBody);
      page.items.forEach(function (entry) { auditBody.appendChild(renderAuditRow(entry)); });
      $("audit-empty").hidden = page.items.length !== 0;
      var from = page.total === 0 ? 0 : page.offset + 1;
      var to = page.offset + page.items.length;
      $("audit-summary").textContent = "Showing " + from + "-" + to + " of " + formatNumber(page.total);
      $("audit-prev").disabled = page.offset === 0;
      $("audit-next").disabled = page.offset + page.items.length >= page.total;
      loaded.audit = true;
    }
  
    $("audit-action").addEventListener("change", function () {
      auditState.offset = 0;
      loadAudit();
    });
    $("audit-refresh").addEventListener("click", function () { loadAudit(); });
    $("audit-prev").addEventListener("click", function () {
      auditState.offset = Math.max(0, auditState.offset - AUDIT_PAGE_SIZE);
      loadAudit();
    });
    $("audit-next").addEventListener("click", function () {
      auditState.offset += AUDIT_PAGE_SIZE;
      loadAudit();
    });
  
    // ---------------------------------------------------------------
    // Start: confirm with the server that this account is an administrator
    // ---------------------------------------------------------------
    async function start() {
      var result;
      try {
        result = await api("GET", "/admin/me");
      } catch (error) {
        $("ad-loading").textContent = "Could not reach the server. Is it running?";
        return;
      }
      if (!result) { return; } // redirected (not logged in, or not an administrator)
      if (result.status !== 200 || !result.data || result.data.role !== "admin") {
        goToUserDashboard();
        return;
      }
      me = result.data;
      renderProfile();
      $("ad-loading").hidden = true;
      $("ad-app").hidden = false;
      var wanted = window.location.hash.replace("#", "");
      showView(VIEW_TITLES[wanted] ? wanted : "overview");
    }
  
    start();
  })();