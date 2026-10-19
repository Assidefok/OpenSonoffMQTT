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
function setBadge(id, label, ok) {
  const badge = $(id);
  badge.textContent = label;
  badge.className = "badge " + (ok ? "ok" : "bad");
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
    id.textContent = device.deviceid;
    info.append(name, id);
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

async function refreshStatus() {
  try {
    const status = await api("api/status");
    setBadge("badge-ewelink", status.ewelink.connected ? "eWeLink: connected" : "eWeLink: offline", status.ewelink.connected);
    setBadge("badge-mqtt", status.mqtt.connected ? "MQTT: connected" : "MQTT: offline", status.mqtt.connected);
    renderDevices(status.devices || []);
    if (!status.ewelink.connected && status.ewelink.error) {
      showToast("eWeLink: " + status.ewelink.error, "bad");
    }
  } catch (error) {
    setBadge("badge-ewelink", "eWeLink: ?", false);
    setBadge("badge-mqtt", "MQTT: ?", false);
  }
}

// ----------------------------------------------------------------------- logs
async function refreshLogs() {
  const details = document.querySelector(".logs details");
  if (!details || !details.open) return;
  try {
    const logs = await api("api/logs");
    const pre = $("logs");
    pre.textContent = (logs.lines || []).join("\n");
    pre.scrollTop = pre.scrollHeight;
  } catch (error) {
    /* ignore log refresh errors */
  }
}

// ---------------------------------------------------------------------- start
$("config-form").addEventListener("submit", saveConfig);
document.querySelector(".logs details").addEventListener("toggle", refreshLogs);

loadConfig().catch((error) => showToast("Can't load config: " + error.message, "bad"));
refreshStatus();
setInterval(refreshStatus, 5000);
setInterval(refreshLogs, 5000);
