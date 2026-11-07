(function () {
  "use strict";

  var TOKEN_KEY = "meditrack_token";

  // Decides where a logged-in person belongs. Administrators go to the admin
  // dashboard and everyone else to their own dashboard. The server decides:
  // /admin/me answers 200 only for an administrator account.
  // Returns null when the token is not valid any more.
  async function destinationFor(token) {
    try {
      var response = await fetch("/admin/me", {
        headers: { Authorization: "Bearer " + token }
      });
      if (response.status === 200) { return "/admin"; }
      if (response.status === 401) { return null; }
    } catch (error) {
      // The server could not be reached. The user dashboard re-checks the token.
    }
    return "/dashboard";
  }

  // Already logged in? Go straight to the right dashboard.
  // (Each dashboard re-checks the token and sends you back here if it is invalid.)
  var savedToken = sessionStorage.getItem(TOKEN_KEY);
  if (savedToken) {
    destinationFor(savedToken).then(function (destination) {
      if (destination) {
        window.location.replace(destination);
      } else {
        sessionStorage.removeItem(TOKEN_KEY);
      }
    });
  }

  var loginForm = document.getElementById("login-form");
  var signupForm = document.getElementById("signup-form");
  var messageBox = document.getElementById("message");

  function showMessage(text, kind) {
    messageBox.textContent = text; // textContent keeps the text safe
    messageBox.className = "alert alert-" + kind;
  }

  function clearMessage() {
    messageBox.textContent = "";
    messageBox.className = "alert d-none";
  }

  function clearInvalid(form) {
    form.querySelectorAll(".is-invalid").forEach(function (input) {
      input.classList.remove("is-invalid");
    });
  }

  function showForm(which) {
    clearMessage();
    clearInvalid(loginForm);
    clearInvalid(signupForm);
    loginForm.classList.toggle("d-none", which !== "login");
    signupForm.classList.toggle("d-none", which !== "signup");
  }

  // Disables a submit button and changes its label while a request is running.
  function setBusy(form, busy, busyLabel) {
    var button = form.querySelector("button[type='submit']");
    if (!button) { return; }
    if (busy) {
      button.dataset.label = button.textContent;
      button.textContent = busyLabel;
      button.disabled = true;
    } else {
      if (button.dataset.label) { button.textContent = button.dataset.label; }
      button.disabled = false;
    }
  }

  // Simple checks before sending. The server still checks everything again.
  // checks: [{ input, ok, message }]. Returns true when every check passes.
  function validate(checks) {
    var firstProblem = null;
    checks.forEach(function (check) {
      var bad = !check.ok;
      check.input.classList.toggle("is-invalid", bad);
      if (bad && !firstProblem) { firstProblem = check; }
    });
    if (firstProblem) {
      showMessage(firstProblem.message, "danger");
      firstProblem.input.focus();
      return false;
    }
    return true;
  }

  function looksLikeEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  async function postJson(url, body) {
    var response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    var data = null;
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
    return { status: response.status, data: data };
  }

  async function logIn(email, password) {
    var result = await postJson("/auth/login", { email: email, password: password });
    if (result.status === 200 && result.data && result.data.access_token) {
      sessionStorage.setItem(TOKEN_KEY, result.data.access_token);
      var destination = await destinationFor(result.data.access_token);
      window.location.replace(destination || "/dashboard");
      return true;
    }
    if (result.status === 401) {
      showMessage("Incorrect email or password.", "danger");
    } else if (result.status === 422) {
      showMessage("Please enter a valid email and password.", "danger");
    } else {
      showMessage("Something went wrong. Please try again.", "danger");
    }
    return false;
  }

  document.getElementById("show-signup").addEventListener("click", function () {
    showForm("signup");
  });
  document.getElementById("show-login").addEventListener("click", function () {
    showForm("login");
  });

  // Show / hide password buttons.
  document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
    button.addEventListener("click", function () {
      var input = document.getElementById(button.getAttribute("data-toggle-password"));
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-pressed", show ? "true" : "false");
    });
  });

  // Remove the red border as soon as the person starts correcting a field.
  document.querySelectorAll("input").forEach(function (input) {
    input.addEventListener("input", function () {
      input.classList.remove("is-invalid");
    });
  });

  loginForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    clearMessage();
    var emailField = document.getElementById("login-email");
    var passwordField = document.getElementById("login-password");
    var email = emailField.value.trim();
    var password = passwordField.value;

    var ok = validate([
      { input: emailField, ok: looksLikeEmail(email), message: "Please enter a valid email address." },
      { input: passwordField, ok: password !== "", message: "Please enter your password." }
    ]);
    if (!ok) { return; }

    setBusy(loginForm, true, "Logging in...");
    try {
      await logIn(email, password);
    } catch (error) {
      showMessage("Could not reach the server. Is it running?", "danger");
    } finally {
      setBusy(loginForm, false);
    }
  });

  signupForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    clearMessage();
    var nameField = document.getElementById("signup-name");
    var emailField = document.getElementById("signup-email");
    var passwordField = document.getElementById("signup-password");
    var fullName = nameField.value.trim();
    var email = emailField.value.trim();
    var password = passwordField.value;

    var ok = validate([
      { input: nameField, ok: fullName !== "", message: "Please enter your full name." },
      { input: emailField, ok: looksLikeEmail(email), message: "Please enter a valid email address." },
      {
        input: passwordField,
        ok: password.length >= 8 && password.length <= 128,
        message: "The password must be between 8 and 128 characters."
      }
    ]);
    if (!ok) { return; }

    setBusy(signupForm, true, "Creating account...");
    try {
      var result = await postJson("/auth/signup", {
        full_name: fullName,
        email: email,
        password: password
      });

      if (result.status === 201) {
        await logIn(email, password);
      } else if (result.status === 409) {
        showMessage("That email is already registered. Try logging in.", "warning");
      } else if (result.status === 422) {
        showMessage("Please check your details. The password needs at least 8 characters.", "danger");
      } else {
        showMessage("Something went wrong. Please try again.", "danger");
      }
    } catch (error) {
      showMessage("Could not reach the server. Is it running?", "danger");
    } finally {
      setBusy(signupForm, false);
    }
  });
})();