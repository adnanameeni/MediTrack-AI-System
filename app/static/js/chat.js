
(function () {
    "use strict";

    var dashboard = window.MediTrackDashboard;

    if (!dashboard || !dashboard.api || window.MediTrackChat) {
        return;
    }

    var conversationId = null;
    var busy = false;

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function icon(name) {
        var icons = {
            chat: [
                ["path", { d: "M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8A8.5 8.5 0 0 1 8.7 3.9a8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z" }]
            ],
            close: [
                ["path", { d: "m18 6-12 12M6 6l12 12" }]
            ],
            send: [
                ["path", { d: "m22 2-7 20-4-9-9-4Z" }],
                ["path", { d: "M22 2 11 13" }]
            ],
            plus: [
                ["path", { d: "M12 5v14M5 12h14" }]
            ],
            history: [
                ["path", { d: "M3 12a9 9 0 1 0 3-6.7L3 8" }],
                ["path", { d: "M3 3v5h5" }],
                ["path", { d: "M12 7v5l3 2" }]
            ],
            trash: [
                ["path", { d: "M3 6h18M8 6V4h8v2m3 0-1 14H6L5 6m4 4v6m6-6v6" }]
            ],
            bot: [
                ["rect", { x: "3", y: "7", width: "18", height: "14", rx: "4" }],
                ["path", { d: "M12 3v4" }],
                ["path", { d: "M8 13h.01M16 13h.01M9 17h6" }]
            ]
        };

        var svgNS = "http://www.w3.org/2000/svg";
        var svg = document.createElementNS(svgNS, "svg");

        svg.setAttribute("viewBox", "0 0 24 24");
        svg.setAttribute("width", "20");
        svg.setAttribute("height", "20");
        svg.setAttribute("fill", "none");
        svg.setAttribute("stroke", "currentColor");
        svg.setAttribute("stroke-width", "1.8");
        svg.setAttribute("stroke-linecap", "round");
        svg.setAttribute("stroke-linejoin", "round");

        var elements = icons[name] || icons.bot;

        elements.forEach(function (item) {
            var child = document.createElementNS(svgNS, item[0]);

            Object.keys(item[1]).forEach(function (attribute) {
                child.setAttribute(attribute, item[1][attribute]);
            });

            svg.appendChild(child);
        });

        return svg;
    }

    function button(className, label, iconName) {
        var btn = el("button", className);
        btn.type = "button";
        btn.setAttribute("aria-label", label);
        btn.title = label;
        if (iconName) btn.appendChild(icon(iconName));
        return btn;
    }

    // Load the assistant stylesheet without requiring dashboard.html changes.
    if (!document.querySelector('link[data-medi-chat-css]')) {
        var css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = "/static/css/chat.css";
        css.setAttribute("data-medi-chat-css", "true");
        document.head.appendChild(css);
    }

    // Floating launcher
    var launcher = button("medi-chat-launcher", "Open AI Assistant", "chat");
    launcher.id = "medi-chat-launcher";
    launcher.appendChild(el("span", "medi-chat-launcher-dot"));

    // Main chat panel
    var panel = el("section", "medi-chat-panel");
    panel.id = "medi-chat-panel";
    panel.setAttribute("aria-label", "MediTrack AI Assistant");
    panel.setAttribute("aria-hidden", "true");

    // Header
    var header = el("div", "medi-chat-header");

    var brand = el("div", "medi-chat-brand");
    var brandIcon = el("div", "medi-chat-brand-icon");
    brandIcon.appendChild(icon("bot"));

    var brandText = el("div", "medi-chat-brand-text");
    brandText.appendChild(el("div", "medi-chat-title", "MediTrack AI"));
    var status = el("div", "medi-chat-status");
    status.appendChild(el("span", "medi-chat-status-dot"));
    status.appendChild(el("span", "", "Health Assistant"));
    brandText.appendChild(status);

    brand.appendChild(brandIcon);
    brand.appendChild(brandText);

    var headerActions = el("div", "medi-chat-header-actions");
    var historyButton = button("medi-chat-icon-button", "Conversation history", "history");
    var newButton = button("medi-chat-icon-button", "New conversation", "plus");
    var closeButton = button("medi-chat-icon-button", "Close assistant", "close");

    headerActions.appendChild(historyButton);
    headerActions.appendChild(newButton);
    headerActions.appendChild(closeButton);
    header.appendChild(brand);
    header.appendChild(headerActions);

    // History section
    var historyArea = el("div", "medi-chat-history");
    historyArea.hidden = true;

    var pastSelect = el("select", "medi-chat-history-select");
    pastSelect.setAttribute("aria-label", "Past conversations");

    var deleteButton = button("medi-chat-delete-button", "Delete selected conversation", "trash");
    deleteButton.appendChild(el("span", "", "Delete"));

    historyArea.appendChild(pastSelect);
    historyArea.appendChild(deleteButton);

    // Messages
    var messagesBox = el("div", "medi-chat-messages");
    messagesBox.setAttribute("aria-live", "polite");

    var welcome = el("div", "medi-chat-welcome");
    var welcomeIcon = el("div", "medi-chat-welcome-icon");
    welcomeIcon.appendChild(icon("bot"));
    welcome.appendChild(welcomeIcon);
    welcome.appendChild(el("h3", "", "How may I help you?"));
    welcome.appendChild(el(
        "p",
        "",
        "Ask about your recorded health information and explore summaries of your health trends."
    ));

    var disclaimer = el(
        "div",
        "medi-chat-disclaimer",
        "This assistant summarizes recorded readings and provides general information. It does not diagnose conditions or recommend medicines."
    );

    // Error area
    var errorBox = el("div", "medi-chat-error");
    errorBox.hidden = true;

    // Composer
    var composer = el("form", "medi-chat-composer");
    var input = el("textarea", "medi-chat-input");
    input.rows = 1;
    input.maxLength = 1000;
    input.placeholder = "Ask about your recorded readings...";
    input.setAttribute("aria-label", "Your question");

    var sendButton = button("medi-chat-send-button", "Send message", "send");
    sendButton.type = "submit";

    var composerHint = el("div", "medi-chat-composer-hint", "Your health information is not a substitute for professional medical advice.");

    composer.appendChild(input);
    composer.appendChild(sendButton);

    panel.appendChild(header);
    panel.appendChild(historyArea);
    panel.appendChild(messagesBox);
    panel.appendChild(errorBox);
    panel.appendChild(disclaimer);
    panel.appendChild(composer);
    panel.appendChild(composerHint);

    document.body.appendChild(launcher);
    document.body.appendChild(panel);

    function openPanel() {
        panel.classList.add("is-open");
        panel.setAttribute("aria-hidden", "false");
        launcher.classList.add("is-hidden");
        input.focus();
    }

    function closePanel() {
        panel.classList.remove("is-open");
        panel.setAttribute("aria-hidden", "true");
        launcher.classList.remove("is-hidden");
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
    }

    function clearError() {
        errorBox.textContent = "";
        errorBox.hidden = true;
    }

    function scrollDown() {
        messagesBox.scrollTop = messagesBox.scrollHeight;
    }

    function showWelcome() {
        messagesBox.replaceChildren(welcome);
    }

    function addBubble(role, text) {
        var isUser = role === "user";
        var row = el("div", "medi-chat-message-row " + (isUser ? "is-user" : "is-assistant"));

        if (!isUser) {
            var avatar = el("div", "medi-chat-message-avatar");
            avatar.appendChild(icon("bot"));
            row.appendChild(avatar);
        }

        var bubble = el("div", "medi-chat-bubble " + (isUser ? "user-bubble" : "assistant-bubble"));
        bubble.textContent = text;
        row.appendChild(bubble);

        messagesBox.appendChild(row);
        scrollDown();

        return { row: row, bubble: bubble };
    }

    function setBusy(value) {
        busy = value;
        input.disabled = value;
        sendButton.disabled = value;
        newButton.disabled = value;
        historyButton.disabled = value;
        deleteButton.disabled = value;
        pastSelect.disabled = value;
        sendButton.classList.toggle("is-loading", value);
    }

    function offsetMinutes() {
        return -new Date().getTimezoneOffset();
    }

    function renderMessages(messages) {
        messagesBox.replaceChildren();

        if (!messages || messages.length === 0) {
            showWelcome();
            return;
        }

        messages.forEach(function (message) {
            addBubble(message.role, message.content);
        });
    }

    async function loadConversations(selectedId) {
        try {
            var result = await dashboard.api("GET", "/chat/conversations");
            if (!result || result.status !== 200) return;

            pastSelect.replaceChildren();

            var first = el("option", "", "Select a conversation...");
            first.value = "";
            pastSelect.appendChild(first);

            result.data.forEach(function (conversation) {
                var option = el("option", "", conversation.title);
                option.value = String(conversation.id);
                pastSelect.appendChild(option);
            });

            pastSelect.value = selectedId === null ? "" : String(selectedId);
        } catch (error) {
            // Conversation history is optional; messaging remains available.
        }
    }

    function newConversation() {
        conversationId = null;
        pastSelect.value = "";
        clearError();
        renderMessages([]);
        input.value = "";
        input.focus();
    }

    async function openConversation(id) {
        clearError();
        setBusy(true);

        try {
            var result = await dashboard.api("GET", "/chat/conversations/" + id);
            if (!result) return;

            if (result.status === 200) {
                conversationId = id;
                renderMessages(result.data.messages);
            } else {
                showError("That conversation could not be opened.");
                newConversation();
                await loadConversations(null);
            }
        } catch (error) {
            showError("Could not reach the server. Please try again.");
        } finally {
            setBusy(false);
        }
    }

    async function deleteConversation() {
        if (conversationId === null) return;

        if (!window.confirm("Delete this conversation?")) return;

        clearError();
        setBusy(true);

        try {
            var result = await dashboard.api("DELETE", "/chat/conversations/" + conversationId);
            if (!result) return;

            if (result.status === 204 || result.status === 404) {
                newConversation();
                await loadConversations(null);
            } else {
                showError("Could not delete the conversation. Please try again.");
            }
        } catch (error) {
            showError("Could not reach the server. Please try again.");
        } finally {
            setBusy(false);
        }
    }

    async function send(text) {
        var message = (text || "").trim();

        if (busy || message === "") return;

        clearError();
        setBusy(true);

        if (conversationId === null && messagesBox.contains(welcome)) {
            messagesBox.replaceChildren();
        }

        var userBubble = addBubble("user", message);
        var waiting = addBubble("assistant", "Thinking...");

        var payload = {
            message: message,
            offset_minutes: offsetMinutes()
        };

        if (conversationId !== null) {
            payload.conversation_id = conversationId;
        }

        try {
            var result = await dashboard.api("POST", "/chat/messages", payload);
            if (!result) return;

            if (result.status === 200) {
                waiting.bubble.textContent = result.data.assistant_message.content;
                conversationId = result.data.conversation_id;
                input.value = "";
                input.style.height = "auto";
                scrollDown();
                await loadConversations(conversationId);
                return;
            }

            userBubble.row.remove();
            waiting.row.remove();

            if (messagesBox.children.length === 0) showWelcome();

            if (result.status === 503) {
                showError("The AI assistant is not configured. Please check the server settings.");
            } else if (result.status === 422) {
                showError("Please enter a question between 1 and 1000 characters.");
            } else if (result.status === 404) {
                showError("That conversation no longer exists. A new conversation has been started.");
                newConversation();
                await loadConversations(null);
            } else {
                showError("Something went wrong. Please try again.");
            }
        } catch (error) {
            userBubble.row.remove();
            waiting.row.remove();

            if (messagesBox.children.length === 0) showWelcome();

            showError("Could not reach the server. Please check your connection.");
        } finally {
            setBusy(false);
        }
    }

    // Events
    launcher.addEventListener("click", openPanel);
    closeButton.addEventListener("click", closePanel);
    newButton.addEventListener("click", newConversation);

    historyButton.addEventListener("click", function () {
        historyArea.hidden = !historyArea.hidden;
        if (!historyArea.hidden) loadConversations(conversationId);
    });

    deleteButton.addEventListener("click", deleteConversation);

    pastSelect.addEventListener("change", function () {
        if (pastSelect.value === "") {
            newConversation();
        } else {
            openConversation(Number(pastSelect.value));
        }
    });

    composer.addEventListener("submit", function (event) {
        event.preventDefault();
        send(input.value);
    });

    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            composer.requestSubmit();
        }
    });

    input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 110) + "px";
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && panel.classList.contains("is-open")) {
            closePanel();
        }
    });

    showWelcome();
    loadConversations(null);

    window.MediTrackChat = {
        send: send,
        open: openPanel,
        close: closePanel
    };
})();
