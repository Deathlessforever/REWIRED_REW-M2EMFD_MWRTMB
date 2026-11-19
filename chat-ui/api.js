(function () {
  const apiBase = String(window.CHITMIRROR_API_BASE || "").replace(/\/+$/, "");

  async function request(path, options) {
    let response;
    try {
      response = await fetch(apiBase + path, options);
    } catch {
      throw new Error("The API is unavailable. Check the connection and try again.");
    }

    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("The API returned an unreadable response (" + response.status + ").");
    }

    if (!response.ok) {
      const message = payload && payload.error && payload.error.message;
      throw new Error(message || "The API request failed (" + response.status + ").");
    }
    return payload;
  }

  function getHealth() {
    return request("/health", {headers: {Accept: "application/json"}});
  }

  function getState(role, memberId) {
    const query = new URLSearchParams({role: role});
    if (memberId) query.set("member_id", memberId);
    return request("/state?" + query.toString(), {
      headers: {Accept: "application/json"},
      cache: "no-store",
    });
  }

  function sendMessage(sender, text) {
    const body = new FormData();
    body.append("sender", sender);
    body.append("text", text);
    return request("/message", {method: "POST", headers: {Accept: "application/json"}, body: body});
  }

  function submitReview(review) {
    return request("/review", {
      method: "POST",
      headers: {Accept: "application/json", "Content-Type": "application/json"},
      body: JSON.stringify(review),
    });
  }

  window.ChitMirrorApi = Object.freeze({getHealth, getState, sendMessage, submitReview});
})();
