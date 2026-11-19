(() => {
  const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[character]));
  }

  function asNumber(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  }

  function formatINR(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? currency.format(parsed / 100) : "—";
  }

  function deriveKpis(state) {
    const counters = state && typeof state.counters === "object" && state.counters !== null ? state.counters : {};
    const collectedPaise = asNumber(counters.collected_paise);
    const paid = asNumber(counters.paid);
    const totalMembers = asNumber(counters.total_members);
    const needsReview = asNumber(counters.needs_review);
    const overdue = asNumber(counters.overdue);
    return {
      collectedPaise,
      collected: formatINR(collectedPaise),
      paid,
      totalMembers,
      needsReview,
      overdue,
      verifiedPercent: totalMembers ? Math.round((paid / totalMembers) * 100) : 0
    };
  }

  function getMembers(state) {
    if (!state || !Array.isArray(state.members)) return [];
    return state.members.filter(member => member && typeof member.id === "string");
  }

  function getMonths(state) {
    if (!state || !Array.isArray(state.months)) return [];
    return [...new Set(state.months.map(Number).filter(Number.isInteger))].sort((a, b) => a - b);
  }

  function getBubbles(state) {
    if (!state || !Array.isArray(state.private_bubbles)) return [];
    return state.private_bubbles.filter(bubble => bubble && typeof bubble === "object");
  }

  function memberLabel(state, memberId) {
    const member = getMembers(state).find(item => item.id === memberId);
    return member ? member.name : memberId || "Unknown member";
  }

  function entryFor(state, memberId, month) {
    if (!state || !Array.isArray(state.ledger)) return null;
    return state.ledger.find(entry => entry && entry.member_id === memberId && Number(entry.month) === Number(month)) || null;
  }

  function personalLedger(state, memberId) {
    if (!state || !Array.isArray(state.ledger)) return [];
    return state.ledger.filter(entry => entry && entry.member_id === memberId);
  }

  function forRole(state, role, memberId) {
    if (!state || role !== "member") return state;
    const selected = getMembers(state).find(member => member.id === memberId) || getMembers(state)[0] || null;
    const bubbles = getBubbles(state).filter(bubble => !bubble.member_id || bubble.member_id === selected?.id || bubble.member_id === memberId);
    return {
      ...state,
      member: selected,
      flags: [],
      overdue: [],
      audit_log: [],
      private_bubbles: bubbles
    };
  }

  function clampPollMs(value) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return 1500;
    return Math.min(2000, Math.max(1000, Math.round(parsed)));
  }

  window.ChitMirrorState = {
    escapeHtml,
    formatINR,
    moneyFromPaise: formatINR,
    deriveKpis,
    getMembers,
    getMonths,
    getBubbles,
    memberLabel,
    entryFor,
    personalLedger,
    forRole,
    clampPollMs
  };
})();
