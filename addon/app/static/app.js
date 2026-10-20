// OpenSonoffMQTT web UI. Plain vanilla JS, no external dependencies.
"use strict";

const BASE = location.pathname.endsWith("/")
  ? location.pathname
  : location.pathname.replace(/[^/]*$/, "");

const $ = (id) => document.getElementById(id);

function api(path, options) {
  return fetch(BASE + path, options).then(async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || data.error || `HTTP ${response.status}`);
    }
    return data;
  });
}

function showToast(message, kind) {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = "toast" + (kind ? " " + kind : "");
  if (kind === "ok") {
    setTimeout(() => {
      if (toast.textContent === message) {
        toast.textContent = "";
        toast.className = "toast";
      }
    }, 6000);
  }
}

// ---------------------------------------------------------------------- tabs
function showTab(name, push) {
  const valid = ["devices", "config", "mqtt", "logs"];
  if (!valid.includes(name)) name = "devices";

  for (const tab of document.querySelectorAll(".tab")) {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.hidden = panel.id !== "panel-" + name;
  }
  if (push && location.hash !== "#" + name) {
    history.replaceState(null, "", "#" + name);
  }
  if (name === "logs") refreshLogs();
  if (name === "mqtt") refreshMessages();
}

// ---------------------------------------------------------------- config form
async function loadConfig() {
  const config = await api("api/config");
  $("ew-username").value = config.ewelink.username || "";
  $("ew-country").value = config.ewelink.country_code || "";
  $("ew-password").value = "";
  $("ew-password").placeholder = config.ewelink.has_password
    ? "•••••••• (saved, leave empty to keep)"
    : "Password";

  $("mq-host").value = config.mqtt.host || "";
  $("mq-port").value = config.mqtt.port || 1883;
  $("mq-username").value = config.mqtt.username || "";
  $("mq-password").value = "";
  $("mq-password").placeholder = config.mqtt.has_password
    ? "•••••••• (saved, leave empty to keep)"
    : "Password";
  $("mq-tls").checked = Boolean(config.mqtt.tls);
  $("mq-retain").checked = Boolean(config.mqtt.retain);
  $("mq-prefix").value = config.mqtt.prefix || "sonoff";
  $("mq-discovery").checked = config.mqtt.discovery !== false;
  $("mq-discovery-prefix").value =
    config.mqtt.discovery_prefix || "homeassistant";
}

function collectConfig() {
  return {
    ewelink: {
      username: $("ew-username").value.trim(),
      password: $("ew-password").value,
      country_code: $("ew-country").value.trim(),
    },
    mqtt: {
      host: $("mq-host").value.trim(),
      port: parseInt($("mq-port").value, 10) || 1883,
      username: $("mq-username").value.trim(),
      password: $("mq-password").value,
      tls: $("mq-tls").checked,
      prefix: $("mq-prefix").value.trim() || "sonoff",
      retain: $("mq-retain").checked,
      discovery: $("mq-discovery").checked,
      discovery_prefix:
        $("mq-discovery-prefix").value.trim() || "homeassistant",
    },
  };
}

async function saveConfig(event) {
  event.preventDefault();
  const button = $("save");
  button.disabled = true;
  showToast("Connecting to eWeLink and MQTT…", "");
  try {
    await api("api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectConfig()),
    });
    showToast("Saved. Devices are now published over MQTT.", "ok");
    await refreshStatus();
    await loadConfig();
  } catch (error) {
    showToast("Error: " + error.message, "bad");
  } finally {
    button.disabled = false;
  }
}

// --------------------------------------------------------------- status/devices
function setBadge(id, label, state) {
  const badge = $(id);
  badge.textContent = label;
  badge.className = "badge" + (state === null ? "" : state ? " ok" : " bad");
}

function scaled(value) {
  // eWeLink reports power/voltage/current x100 (0.01 W/V/A).
  const number = Number(value);
  return Number.isFinite(number) ? number / 100 : Number.NaN;
}

function metrics(device) {
  const params = device.params || {};
  const parts = [];
  const power = scaled(params.power);
  if (Number.isFinite(power)) parts.push(power.toFixed(1) + " W");
  const voltage = scaled(params.voltage);
  if (Number.isFinite(voltage)) parts.push(voltage.toFixed(1) + " V");
  const current = scaled(params.current);
  if (Number.isFinite(current)) parts.push(current.toFixed(2) + " A");
  return parts.join(" · ");
}

function renderDevices(devices) {
  const list = $("devices");
  list.textContent = "";
  $("device-count").textContent = devices.length
    ? `${devices.length} device(s)`
    : "";
  $("devices-empty").style.display = devices.length ? "none" : "block";

  for (const device of devices) {
    const item = document.createElement("li");
    item.className = "device" + (device.online ? " online" : "");

    const dot = document.createElement("span");
    dot.className = "dot";
    item.appendChild(dot);

    const info = document.createElement("div");
    info.className = "info";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = device.name || device.deviceid;
    const id = document.createElement("div");
    id.className = "id";
    id.textContent = device.deviceid + (device.uiid ? " · UIID " + device.uiid : "");
    info.append(name, id);

    const values = metrics(device);
    if (values) {
      const detail = document.createElement("div");
      detail.className = "values";
      detail.textContent = values;
      info.appendChild(detail);
    }
    item.appendChild(info);

    const sw = device.params && device.params.switch;
    if (typeof sw === "string") {
      const on = sw === "on";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "toggle" + (on ? " on" : "");
      button.textContent = on ? "ON" : "OFF";
      button.addEventListener("click", () => toggleDevice(device.deviceid, !on, button));
      item.appendChild(button);
    }

    list.appendChild(item);
  }
}

async function toggleDevice(deviceid, turnOn, button) {
  button.disabled = true;
  try {
    await api(`api/devices/${encodeURIComponent(deviceid)}/state`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params: { switch: turnOn ? "on" : "off" } }),
    });
    setTimeout(refreshStatus, 700);
  } catch (error) {
    showToast("Error: " + error.message, "bad");
  } finally {
    button.disabled = false;
  }
}

function renderStatus(status) {
  const ewelink = status.ewelink || {};
  const mqtt = status.mqtt || {};

  setBadge("badge-ewelink", ewelink.connected ? "eWeLink: connected" : "eWeLink: offline", ewelink.connected);
  setBadge("badge-mqtt", mqtt.connected ? "MQTT: connected" : "MQTT: offline", mqtt.connected);

  if (mqtt.discovery) {
    const entities = mqtt.entities ? ` (${mqtt.entities})` : "";
    setBadge("badge-discovery", "Discovery: on" + entities, true);
  } else {
    setBadge("badge-discovery", "Discovery: off", null);
  }

  $("version").textContent = "v" + (status.version || "?");
  const bits = [];
  if (mqtt.prefix) bits.push("prefix " + mqtt.prefix);
  if (mqtt.discovery) {
    bits.push("HA discovery → " + (mqtt.discovery_prefix || "homeassistant"));
  } else {
    bits.push("HA discovery disabled");
  }
  if (mqtt.entities) bits.push(mqtt.entities + " discovery entities");
  $("statusline").textContent = bits.join(" · ");

  renderDevices(status.devices || []);

  if (!ewelink.connected && ewelink.error) {
    showToast("eWeLink: " + ewelink.error, "bad");
  }
}

async function refreshStatus() {
  try {
    renderStatus(await api("api/status"));
  } catch (error) {
    setBadge("badge-ewelink", "eWeLink: ?", false);
    setBadge("badge-mqtt", "MQTT: ?", false);
    $("statusline").textContent = "Can't read the status: " + error.message;
  }
}

// ----------------------------------------------------------------------- logs
function logsPanelVisible() {
  return !$("panel-logs").hidden;
}

async function refreshLogs() {
  if (!logsPanelVisible()) return;
  try {
    const logs = await api("api/logs");
    const pre = $("logs");
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    pre.textContent = (logs.lines || []).join("\n");
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  } catch (error) {
    /* ignore log refresh errors */
  }
}

// ---------------------------------------------------------------------- mqtt
function mqttPanelVisible() {
  return !$("panel-mqtt").hidden;
}

async function refreshMessages() {
  if (!mqttPanelVisible()) return;
  try {
    const data = await api("api/messages");
    const pre = $("mqtt-messages");
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    const lines = (data.messages || []).map(
      (message) => `${message.time}  ${message.topic}  ${message.payload}`
    );
    pre.textContent = lines.length
      ? lines.join("\n")
      : "Nothing published yet — wait for the first eWeLink update.";
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  } catch (error) {
    /* ignore message refresh errors */
  }
}

// ---------------------------------------------------------------------- start
$("config-form").addEventListener("submit", saveConfig);

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => showTab(tab.dataset.tab, true));
}
window.addEventListener("hashchange", () => showTab(location.hash.slice(1), false));

showTab(location.hash.slice(1), false);
loadConfig().catch((error) => showToast("Can't load config: " + error.message, "bad"));
refreshStatus();
setInterval(refreshStatus, 5000);
setInterval(refreshLogs, 3000);
setInterval(refreshMessages, 2000);
