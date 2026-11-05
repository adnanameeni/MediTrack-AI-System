(function () {
    "use strict";
  
    var TOKEN_KEY = "meditrack_token";
  
    // Already logged in? Go straight to the dashboard.
    // (The dashboard re-checks the token and sends you back here if it is invalid.)
    if (sessionStorage.getItem(TOKEN_KEY)) {
      window.location.replace("/dashboard");
      return;
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
  
    function showForm(which) {
      clearMessage();
      loginForm.classList.toggle("d-none", which !== "login");
      signupForm.classList.toggle("d-none", which !== "signup");
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
        window.location.replace("/dashboard");
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
  
    loginForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      clearMessage();
      var email = document.getElementById("login-email").value.trim();
      var password = document.getElementById("login-password").value;
      try {
        await logIn(email, password);
      } catch (error) {
        showMessage("Could not reach the server. Is it running?", "danger");
      }
    });
  
    signupForm.addEventListener("submit", async function (event) {
      event.preventDefault();
      clearMessage();
      var fullName = document.getElementById("signup-name").value.trim();
      var email = document.getElementById("signup-email").value.trim();
      var password = document.getElementById("signup-password").value;
  
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
      }
    });
  })();