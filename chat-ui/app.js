const connection = document.querySelector("#connection");
const senderPicker = document.querySelector("#sender");
const reviewQueue = document.querySelector("#review-queue");
const queueStatus = document.querySelector("#queue-status");
const reminderSection = document.querySelector("#reminder-section");
const reminderStatus = document.querySelector("#reminder-status");
const reminderFeed = document.querySelector("#reminder-feed");
const reminderCount = document.querySelector("#reminder-count");
const messageList = document.querySelector("#message-list");
const messageInput = document.querySelector("#message-input");
const hintsOutput = document.querySelector("#command-hints");
const notice = document.querySelector("#notice");
const composer = document.querySelector("#composer");
const sendButton = document.querySelector("#send-message");
let members = [];

function apiUrl(path) {
  const base = (window.CHITMIRROR_API_BASE || "").replace(/\/$/, "");
  return base + path;
}

function showNotice(message, isError) {
  notice.textContent = message || "";
  notice.classList.toggle("error", Boolean(isError));
}

async function checkConnection() {
  try {
    const response = await fetch(apiUrl("/health"), {headers: {Accept: "application/json"}});
    const payload = await response.json();
    if (!response.ok || payload.status !== "ok") throw new Error("Health check failed");
    connection.textContent = "Backend connected";
    connection.classList.add("connected");
  } catch {
    connection.textContent = "Backend unavailable — check the server and API URL.";
    connection.classList.add("failed");
  }
}

function addTextBubble(label, text, kind, testId) {
  const article = document.createElement("article");
  article.className = "bubble " + (kind || "server-bubble");
  if (testId) article.dataset.testid = testId;
  const title = document.createElement("span");
  title.className = "bubble-label";
  title.textContent = label;
  const stamp = document.createElement("time");
  const now = new Date();
  stamp.dateTime = now.toISOString();
  stamp.textContent = now.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  const body = document.createElement("p");
  body.textContent = text;
  article.append(title, stamp, body);
  messageList.append(article);
  return article;
}

function addReminderBubble(text, target) {
  const article = document.createElement("article");
  article.className = "bubble reminder-bubble";
  article.dataset.testid = "reminder-bubble";
  article.dataset.memberScoped = "true";
  const title = document.createElement("span");
  title.className = "bubble-label";
  title.textContent = "Private reminder";
  const stamp = document.createElement("time");
  const now = new Date();
  stamp.dateTime = now.toISOString();
  stamp.textContent = now.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  const body = document.createElement("p");
  body.textContent = text || "";
  article.append(title, stamp, body);
  (target || messageList).append(article);
  return article;
}

function clearConversation() {
  Array.from(messageList.children).forEach(function(child, index) {
    if (index > 0) child.remove();
  });
  reminderFeed.replaceChildren();
  reminderCount.textContent = "";
  showNotice("", false);
}

function setSenderOptions() {
  const selected = senderPicker.value || "foreman";
  senderPicker.replaceChildren();
  const foreman = document.createElement("option");
  foreman.value = "foreman";
  foreman.textContent = "Foreman";
  senderPicker.append(foreman);
  members.forEach(function(member) {
    const option = document.createElement("option");
    option.value = member.id;
    option.textContent = member.name;
    senderPicker.append(option);
  });
  senderPicker.value = selected;
  if (!senderPicker.value) senderPicker.value = "foreman";
  reviewQueue.hidden = senderPicker.value !== "foreman";
  reminderSection.hidden = senderPicker.value === "foreman";
}

function renderReviewCard(item) {
  if (!item || typeof item.item_id !== "string" || !item.item_id.trim()) return;
  const existing = reviewQueue.querySelector('[data-item-id="' + CSS.escape(item.item_id) + '"]');
  if (existing) return;
  const member = members.find(function(candidate) { return candidate.id === item.member_id; });
  const article = document.createElement("article");
  article.className = "bubble review-bubble";
  article.dataset.itemId = item.item_id;

  const header = document.createElement("div");
  header.className = "review-card-heading";
  const title = document.createElement("span");
  title.className = "bubble-label";
  title.textContent = "Needs review";
  const badge = document.createElement("span");
  badge.className = "review-badge";
  badge.textContent = "Foreman action";
  header.append(title, badge);

  const details = document.createElement("p");
  details.className = "review-details";
  const detailParts = [];
  if (member) detailParts.push(member.name);
  if (Number.isInteger(Number(item.month))) detailParts.push("Month " + Number(item.month));
  details.textContent = detailParts.join(" · ");

  const reason = document.createElement("p");
  reason.className = "review-reason";
  reason.textContent = item.reason || "A payment was flagged for manual review.";

  const label = document.createElement("label");
  const inputId = "review-reason-" + item.item_id;
  label.htmlFor = inputId;
  label.textContent = "Reason for your decision";
  const textarea = document.createElement("textarea");
  textarea.id = inputId;
  textarea.dataset.testid = "review-reason-" + item.item_id;
  textarea.rows = 2;
  textarea.required = true;
  textarea.placeholder = "Explain the evidence you checked";
  textarea.setAttribute("aria-describedby", "review-error-" + item.item_id);

  const error = document.createElement("p");
  error.className = "field-error";
  error.id = "review-error-" + item.item_id;
  error.setAttribute("aria-live", "polite");

  const actions = document.createElement("div");
  actions.className = "review-actions";
  ["approve", "reject"].forEach(function(decision) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = decision === "approve" ? "approve-button" : "reject-button";
    button.dataset.testid = "review-" + decision + "-" + item.item_id;
    button.textContent = decision === "approve" ? "Approve" : "Reject";
    button.addEventListener("click", function() {
      submitReview(item.item_id, decision, textarea, error, article, actions);
    });
    actions.append(button);
  });

  article.append(header);
  if (details.textContent) article.append(details);
  article.append(reason, label, textarea, error, actions);
  reviewQueue.append(article);
}

async function submitReview(itemId, decision, textarea, error, article, actions) {
  if (senderPicker.value !== "foreman") {
    error.textContent = "Only the foreman can submit a review decision.";
    return;
  }
  const reason = textarea.value.trim();
  if (!reason) {
    error.textContent = "Enter a reason before approving or rejecting.";
    textarea.setAttribute("aria-invalid", "true");
    textarea.focus();
    return;
  }
  textarea.removeAttribute("aria-invalid");
  error.textContent = "";
  Array.from(actions.querySelectorAll("button")).forEach(function(button) { button.disabled = true; });
  try {
    const response = await fetch(apiUrl("/review"), {
      method: "POST",
      headers: {"Accept": "application/json", "Content-Type": "application/json"},
      body: JSON.stringify({item_id: itemId, decision: decision, reason: reason, actor: "foreman"})
    });
    const payload = await response.json().catch(function() { return {}; });
    if (!response.ok) throw new Error(payload.error && payload.error.message ? payload.error.message : "Review request failed (" + response.status + ").");
    if (payload.item_id !== itemId || payload.decision !== decision) throw new Error("The server returned an unexpected review result.");
    article.remove();
    queueStatus.textContent = decision === "approve" ? "Review approved and recorded." : "Review rejected and recorded.";
    showNotice("Decision recorded by the server.", false);
    await loadReviewQueue();
  } catch (requestError) {
    Array.from(actions.querySelectorAll("button")).forEach(function(button) { button.disabled = false; });
    error.textContent = requestError.message || "Could not record this decision. Try again.";
  }
}

function renderBubble(bubble) {
  if (!bubble || typeof bubble !== "object") return;
  if (bubble.type === "reminder") {
    addReminderBubble(bubble.text);
    return;
  }
  if (bubble.type === "text") {
    const text = bubble.text || "";
    if (/^Dues for /.test(text)) {
      addTextBubble("Dues", text, "dues-bubble", "dues-result");
    } else if (/^Statement for /.test(text)) {
      addTextBubble("Statement", text, "statement-bubble", "statement-result");
    } else if (/^(No private reminders|Private reminders for)/.test(text)) {
      addTextBubble("Private reminders", text, "reminder-bubble", "reminder-header");
    } else {
      addTextBubble("ChitMirror", text, "server-bubble");
    }
    return;
  }
  if (bubble.type === "result_card") {
    const summary = [bubble.status || "Payment result", bubble.amount_paise == null ? "" : "₹" + (Number(bubble.amount_paise) / 100).toLocaleString("en-IN", {minimumFractionDigits: 2}), bubble.utr ? "UTR " + bubble.utr : "", bubble.reason || ""].filter(Boolean).join(" · ");
    addTextBubble("Payment result", summary, "result-bubble");
    return;
  }
  if (bubble.type === "review_request") {
    renderReviewCard(bubble);
    addTextBubble("ChitMirror", "A payment was flagged for foreman review.", "server-bubble");
  }
}

async function loadReviewQueue() {
  queueStatus.textContent = "Loading review items…";
  try {
    const response = await fetch(apiUrl("/state?role=foreman"), {headers: {Accept: "application/json"}, cache: "no-store"});
    if (!response.ok) throw new Error("State request failed (" + response.status + ").");
    const state = await response.json();
    if (!state || !Array.isArray(state.members) || !Array.isArray(state.flags)) throw new Error("Shared state response is incomplete.");
    members = state.members;
    setSenderOptions();
    if (senderPicker.value === "foreman") {
      reviewQueue.replaceChildren();
      state.flags.forEach(renderReviewCard);
      queueStatus.textContent = state.flags.length ? state.flags.length + " item" + (state.flags.length === 1 ? "" : "s") + " need foreman review." : "No open review items.";
    } else {
      reviewQueue.replaceChildren();
      queueStatus.textContent = "Review actions are available to the foreman.";
    }
    return state;
  } catch (error) {
    queueStatus.textContent = "Review queue unavailable. " + (error.message || "Check the shared state endpoint.");
    return null;
  }
}

async function loadMemberContext() {
  const memberId = senderPicker.value;
  if (memberId === "foreman") {
    reminderSection.hidden = true;
    reminderFeed.replaceChildren();
    reminderStatus.textContent = "";
    reminderCount.textContent = "";
    return;
  }
  reminderSection.hidden = false;
  reminderFeed.replaceChildren();
  reminderCount.textContent = "";
  reminderStatus.textContent = "Loading private reminders…";
  try {
    const response = await fetch(apiUrl("/state?role=member&member_id=" + encodeURIComponent(memberId)), {headers: {Accept: "application/json"}, cache: "no-store"});
    if (!response.ok) throw new Error("State request failed (" + response.status + ").");
    const state = await response.json();
    if (!state || !Array.isArray(state.private_bubbles)) throw new Error("Shared state response is incomplete.");
    const bubbles = state.private_bubbles.filter(function(bubble) { return bubble && bubble.type === "reminder"; });
    bubbles.forEach(function(bubble) { addReminderBubble(bubble.text, reminderFeed); });
    reminderCount.textContent = bubbles.length ? bubbles.length + (bubbles.length === 1 ? " reminder" : " reminders") : "";
    reminderStatus.textContent = bubbles.length ? "" : "No private reminders for this sender.";
  } catch (error) {
    reminderStatus.textContent = "Private reminders unavailable. " + (error.message || "Check the shared state endpoint.");
  }
}

function parseCommandHints(text) {
  const hints = [];
  const month = /\bmonth\s+(\d+)\b/i.exec(text);
  const name = /\bname\s*[:=]\s*([^,;\n]+)/i.exec(text);
  const discount = /\bdiscount\s*(?:₹|rs\.?\s*|inr\s*)?([\d,]+(?:\.\d{1,2})?)/i.exec(text);
  const memberCommand = /\b(dues?|statement|reminders?)\b/i.exec(text);
  if (memberCommand) hints.push("Selected-sender " + memberCommand[1].toLowerCase());
  if (month) hints.push("Month " + Number(month[1]));
  if (name && name[1].trim()) hints.push("Name " + name[1].trim());
  if (discount) hints.push("Discount ₹" + discount[1].replace(/,/g, ""));
  return hints;
}

function updateCommandHints() {
  const hints = parseCommandHints(messageInput.value);
  if (!hints.length) {
    hintsOutput.hidden = true;
    hintsOutput.textContent = "";
    return;
  }
  hintsOutput.hidden = false;
  hintsOutput.textContent = "Hints only — server validates: " + hints.join(" · ");
}

senderPicker.addEventListener("change", function() {
  clearConversation();
  setSenderOptions();
  updateCommandHints();
  loadMemberContext();
});
messageInput.addEventListener("input", updateCommandHints);
document.querySelector("#refresh-queue").addEventListener("click", loadReviewQueue);

composer.addEventListener("submit", async function(event) {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text) {
    messageInput.focus();
    return;
  }
  sendButton.disabled = true;
  showNotice("", false);
  try {
    const response = await fetch(apiUrl("/message"), {
      method: "POST",
      headers: {"Accept": "application/json", "Content-Type": "application/json"},
      body: JSON.stringify({sender: senderPicker.value, text: text})
    });
    const payload = await response.json().catch(function() { return {}; });
    if (!response.ok) throw new Error(payload.error && payload.error.message ? payload.error.message : "Message request failed (" + response.status + ").");
    if (!payload || !Array.isArray(payload.bubbles)) throw new Error("The server returned an invalid chat response.");
    addTextBubble(senderPicker.options[senderPicker.selectedIndex].text, text, "member-bubble");
    if (!payload.bubbles.length) {
      addTextBubble("ChitMirror", "No details are available for this command.", "server-bubble", "empty-result");
      showNotice("No details are available for this command.", false);
    }
    payload.bubbles.forEach(renderBubble);
    messageInput.value = "";
    updateCommandHints();
    messageList.scrollTop = messageList.scrollHeight;
  } catch (error) {
    showNotice(error.message || "Message could not be sent. Try again.", true);
  } finally {
    sendButton.disabled = false;
  }
});

checkConnection();
loadReviewQueue().then(loadMemberContext);
