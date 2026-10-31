(async () => {
  const notice = document.getElementById("notice");
  const storageKey = "hirara-browser-session";
  const form = document.querySelector("form");
  const status = document.getElementById("status");
  const notify = (message) => {
    notice.textContent = message;
  };

  function setupPicker() {
    const picker = document.querySelector(".auth-picker");
    if (!picker) return;
    const trigger = picker.querySelector("[role=combobox]");
    const menu = picker.querySelector("[role=listbox]");
    const options = [...menu.querySelectorAll("[role=option]")];
    const mode = form.elements.mode;
    const selectedIndex = () =>
      Math.max(
        0,
        options.findIndex((o) => o.dataset.value === mode.value),
      );
    const close = (restoreFocus = false) => {
      menu.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
      if (restoreFocus) trigger.focus();
    };
    const open = (index = selectedIndex()) => {
      menu.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      options[index].focus();
    };
    const choose = (option) => {
      mode.value = option.dataset.value;
      picker.querySelector(".select-value").textContent =
        option.querySelector(".select-value").textContent;
      picker.querySelector(".select-description").textContent =
        option.querySelector(".select-description").textContent;
      picker
        .querySelector(".select-icon")
        .replaceChildren(option.querySelector("svg").cloneNode(true));
      options.forEach((o) =>
        o.setAttribute("aria-selected", String(o === option)),
      );
      mode.dispatchEvent(new Event("change", { bubbles: true }));
      close(true);
    };
    trigger.addEventListener("click", () => (menu.hidden ? open() : close()));
    trigger.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        open(
          event.key === "End" || event.key === "ArrowUp"
            ? options.length - 1
            : selectedIndex(),
        );
      } else if (event.key === "Escape") close(true);
    });
    options.forEach((option, index) => {
      option.addEventListener("click", () => choose(option));
      option.addEventListener("keydown", (event) => {
        let next;
        if (event.key === "ArrowDown") next = (index + 1) % options.length;
        if (event.key === "ArrowUp")
          next = (index + options.length - 1) % options.length;
        if (event.key === "Home") next = 0;
        if (event.key === "End") next = options.length - 1;
        if (next !== undefined) {
          event.preventDefault();
          options[next].focus();
        }
        if (event.key === "Escape") {
          event.preventDefault();
          close(true);
        }
        if (event.key === "Tab") close();
      });
    });
    document.addEventListener("click", (event) => {
      if (!picker.contains(event.target)) close();
    });
  }

  function setupForm() {
    setupPicker();
    const mode = form.elements.mode;
    const allTools = form.elements.all_tools;
    const tools = form.elements.tools;
    const disclosure = form.querySelector(".disclosure");
    const scope = document.getElementById("tool-scope");
    const fields = () => {
      for (const [name, show] of [
        ["bearer", ["bearer", "api_key"].includes(mode.value)],
        ["header_name", mode.value === "api_key"],
        ["client_id", mode.value === "oauth"],
      ])
        form.elements[name].closest(".field").hidden = !show;
      notify("");
    };
    mode.addEventListener("change", fields);
    fields();
    disclosure.addEventListener("click", () => {
      const opening = scope.hidden;
      scope.hidden = !opening;
      disclosure.setAttribute("aria-expanded", String(opening));
      if (opening) {
        allTools.checked = false;
        tools.focus();
      }
    });
    tools.addEventListener("input", () => {
      if (tools.value.trim()) allTools.checked = false;
    });
    allTools.addEventListener("change", () => {
      if (allTools.checked) {
        tools.value = "";
        scope.hidden = true;
        disclosure.setAttribute("aria-expanded", "false");
      }
      notify("");
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!allTools.checked && !tools.value.trim()) {
        notify("Choose the tools this server can access before connecting.");
        allTools.focus();
        return;
      }
      if (
        ["bearer", "api_key"].includes(mode.value) &&
        !form.elements.bearer.value.trim()
      ) {
        notify(
          mode.value === "api_key"
            ? "Enter your provider API key."
            : "Enter your provider access token.",
        );
        form.elements.bearer.focus();
        return;
      }
      if (mode.value === "api_key" && !form.elements.header_name.value.trim()) {
        notify("Enter the API key header name supplied by your provider.");
        form.elements.header_name.focus();
        return;
      }
      const button = form.querySelector("[type=submit]");
      const label = button.querySelector(".button-label");
      button.disabled = true;
      button.classList.add("is-loading");
      label.textContent = "Connecting…";
      notify("");
      try {
        const response = await fetch(location.pathname, {
          method: "POST",
          headers: {
            Authorization: "Bearer " + localStorage.getItem(storageKey),
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams(new FormData(form)),
        });
        if (!response.ok) {
          const error = await response.json();
          throw Error(error.error || "Connection could not be approved.");
        }
        const content = document.getElementById("content");
        content.innerHTML = await response.text();
        content.classList.add("result-body");
      } catch (error) {
        notify(error.message);
        button.disabled = false;
        button.classList.remove("is-loading");
        label.textContent = "Connect";
      }
    });
  }

  try {
    const ticket = location.hash.slice(1);
    history.replaceState(null, "", location.pathname);
    if (ticket) {
      const response = await fetch("/local/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticket }),
      });
      if (!response.ok)
        throw Error("Browser link expired. Run hirara-connectors open again.");
      localStorage.setItem(storageKey, (await response.json()).token);
    }
    if (!form && !status) return;
    const token = localStorage.getItem(storageKey);
    if (!token) {
      notify(
        "Open your browser session first: run hirara-connectors open on this computer, then reload this page.",
      );
      const button = document.querySelector("[type=submit]");
      if (button) button.disabled = true;
      return;
    }
    if (form) setupForm();
    else {
      const response = await fetch("/local/connections", {
        headers: { Authorization: "Bearer " + token },
      });
      if (!response.ok) {
        localStorage.removeItem(storageKey);
        throw Error(
          "Browser session expired. Run hirara-connectors open again.",
        );
      }
      status.textContent = "Your browser is ready to approve connections.";
      for (const connection of (await response.json()).connections) {
        const row = document.createElement("div");
        row.className = "saved-connection";
        const title = document.createElement("span");
        title.textContent = connection.title;
        const saved = document.createElement("span");
        saved.className = "saved-label";
        saved.textContent = connection.has_credentials ? "Saved" : "Sign-in needed";
        row.append(title, saved);
        document.getElementById("connections").append(row);
      }
    }
  } catch (error) {
    notify(error.message);
  }
})();
