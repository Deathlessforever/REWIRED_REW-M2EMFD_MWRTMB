const connection = document.querySelector("#connection");
const connectionLabel = document.querySelector("#connection-label");

async function checkConnection() {
  const base = window.CHITMIRROR_API_BASE || "";
  try {
    const response = await fetch(`${base}/health`, { headers: { Accept: "application/json" } });
    if (!response.ok || (await response.json()).status !== "ok") throw new Error("Backend health check failed");
    connection.classList.add("connected");
    connectionLabel.textContent = "Backend connected";
  } catch {
    connection.classList.add("failed");
    connectionLabel.textContent = "Backend unavailable · showing sample dashboard";
  }
}

checkConnection();

