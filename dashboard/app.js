const $ = (id) => document.getElementById(id);
const apiBase = window.CHITMIRROR_API_BASE || "";
let evidence = null;
let state = null;
let currentFile = null;
let activeFilter = "all";
let scenarioData = {};
let screenshotManifest = [];

const pageNames = {dashboard:"Dashboard",verify:"Verify payments",ledger:"Group ledger",auction:"Auction",members:"Members",mychit:"My chit",statement:"My statement",reports:"Reports",audit:"Audit log",setup:"Group setup"};

const connection = document.querySelector("#connection");
const connectionLabel = document.querySelector("#connection-label");
async function checkConnection() {
  try {
    const response = await fetch(`${apiBase}/health`, {headers:{Accept:"application/json"}});
    if (!response.ok || (await response.json()).status !== "ok") throw new Error("Health check failed");
    connection.classList.add("connected");
    connectionLabel.textContent = "Backend connected";
  } catch {
    connection.classList.add("failed");
    connectionLabel.textContent = "Backend unavailable · showing sample data";
  }
}
checkConnection();

document.querySelectorAll(".nav button[data-page]").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page)));
document.querySelectorAll("[data-goto]").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.goto)));
document.querySelectorAll(".scenario").forEach((button) => button.addEventListener("click", () => {
  const scenario = scenarioData[button.dataset.scenario];
  if (!scenario) return;
  document.querySelectorAll(".scenario").forEach((item) => item.classList.remove("selected"));
  button.classList.add("selected");
  $("utr").value = scenario.utr;
  $("amount").value = scenario.amount;
  $("date").value = scenario.date;
  $("receiver").value = scenario.receiver;
  $("member").value = scenario.member;
  $("result").className = "result";
  showPage("dashboard");
}));

function showPage(name) {
  document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${name}`));
  document.querySelectorAll(".nav button").forEach((button) => button.classList.toggle("active", button.dataset.page === name));
  if ($("crumbTitle")) $("crumbTitle").textContent = pageNames[name] || "Dashboard";
  window.scrollTo({top:0,behavior:"smooth"});
}

async function request(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {headers:{Accept:"application/json", "Content-Type":"application/json", ...(options.headers||{})}, ...options});
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || body.error || `Request failed (${response.status})`);
  return body;
}

async function loadDemoData() {
  const [snapshot, scenariosResponse, manifestResponse] = await Promise.all([
    request("/api/state"),
    fetch(`${apiBase}/data/scenarios.json`, {headers:{Accept:"application/json"}}),
    fetch(`${apiBase}/data/screenshot_manifest.json`, {headers:{Accept:"application/json"}})
  ]);
  if (!scenariosResponse.ok || !manifestResponse.ok) throw new Error("Demo data files are unavailable");
  evidence = {...snapshot.evidence, group:{...snapshot.evidence.group,members:snapshot.evidence.group.memberCount}};
  state = snapshot.state;
  scenarioData = (await scenariosResponse.json()).scenarios;
  screenshotManifest = (await manifestResponse.json()).screenshots;
  fillMemberPicker();
  render();
}

function fillMemberPicker() {
  const select = $("member");
  if (!select) return;
  const selected = select.value;
  select.innerHTML = evidence.transactions.map((member) => `<option value="${safe(member.memberId)}">${safe(member.memberName)} · ${safe(member.memberId)}</option>`).join("");
  if (evidence.transactions.some((member) => member.memberId === selected)) select.value = selected;
}

function rupee(value) { return "₹" + Number(value || 0).toLocaleString("en-IN"); }
function safe(value) { return String(value ?? "").replace(/[&<>"']/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[character])); }
function badge(status) { const label={verified:"Verified",duplicate:"Duplicate",mismatch:"Rejected",failed:"Rejected",review:"Needs review",pending:"Pending"}[status]||status; return `<span class="status ${safe(status)}">${label}</span>`; }
function table(rows, heads) { return `<table><thead><tr>${heads.map((heading)=>`<th>${heading}</th>`).join("")}</tr></thead><tbody>${rows||'<tr><td colspan="8"><div class="empty">No submissions yet. Try a demo scenario.</div></td></tr>'}</tbody></table>`; }
function paymentRows(list) { return list.map((event)=>`<tr><td class="membername">${safe(event.memberName)}</td><td class="mono">${safe(event.utr||"—")}</td><td>${rupee(event.amount)}</td><td>${badge(event.status)}</td><td>${safe(event.reason)}</td><td>${new Date(event.time).toLocaleString([], {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})}</td></tr>`).join(""); }

function render() {
  if (!evidence || !state) return;
  const transactions=evidence.transactions, payments=state.payments, audit=state.audit, goal=evidence.group.members;
  const verified=new Set(payments.map((payment)=>payment.memberId));
  const total=payments.reduce((sum,payment)=>sum+Number(payment.amount),0);
  const outstanding=audit.filter((event)=>event.status!=="verified").length;
  const percent=Math.round(verified.size/goal*100);
  $("pool").textContent=rupee(total); $("paidCount").textContent=`${verified.size} / ${goal}`;
  $("reviewKpi").textContent=outstanding; $("reviewCount").textContent=outstanding;
  $("overdueKpi").textContent=evidence.overdueMemberIds.filter((id)=>!verified.has(id)).length;
  $("quickVerified").textContent=verified.size; $("quickFlagged").textContent=outstanding;
  $("progressAmount").textContent=rupee(total); $("progressPct").textContent=`${percent}%`;
  $("progressRing").style.setProperty("--progress",`${percent}%`);
  $("readiness").textContent=verified.size>=goal?"Eligible":"Building";
  $("auctionReady").textContent=verified.size>=goal?"All contributions verified · eligible for payout":`Requires ${goal} verified contributions`;
  $("allN").textContent=audit.length;
  $("reviewN").textContent=audit.filter((event)=>["review","pending"].includes(event.status)).length;
  $("rejectN").textContent=audit.filter((event)=>["mismatch","failed","duplicate"].includes(event.status)).length;
  $("ledgerTotal").textContent=`${rupee(total)} collected`;
  const filtered=audit.filter((event)=>activeFilter==="all"||(activeFilter==="review"?["review","pending"].includes(event.status):activeFilter==="mismatch"?["mismatch","failed","duplicate"].includes(event.status):event.status==="pending"));
  $("queueTable").innerHTML=table(paymentRows(filtered),["Member","UTR","Amount","Status","Decision detail","Submitted"]);
  $("recentQueue").innerHTML=table(paymentRows(audit.slice(0,4)),["Member","UTR","Amount","Status"]);
  $("dashboardTrail").innerHTML=audit.length?`<div class="checklist">${audit.slice(0,3).map((event)=>`<div class="check"><i>${event.status==="verified"?"✓":"!"}</i><span><b>${safe(event.memberName)}</b> · ${safe(event.reason)}</span></div>`).join("")}</div>`:'<div class="empty">No payment activity yet.</div>';
  const paidIds=new Set(payments.map((payment)=>payment.memberId));
  const cells=transactions.map((member)=>`<tr><td><span class="membername">${safe(member.memberName)}</span></td>${Array.from({length:evidence.group.tenureMonths},(_,index)=>{const cellClass=index===evidence.group.currentMonth-1?(paidIds.has(member.memberId)?"paid":""):"";return `<td title="Month ${index+1}: ${index===evidence.group.currentMonth-1?(paidIds.has(member.memberId)?"verified":"due"):"pending"}"><span class="cell ${cellClass}"></span></td>`}).join("")}</tr>`).join("");
  $("matrix").innerHTML=`<table class="matrix"><thead><tr><th>Member</th><th colspan="${evidence.group.tenureMonths}">Month (1–${evidence.group.tenureMonths})</th></tr><tr><th></th>${Array.from({length:evidence.group.tenureMonths},(_,index)=>`<th>${index+1}</th>`).join("")}</tr></thead><tbody>${cells}</tbody></table>`;
  const due=evidence.group.netInstalment;
  const ledgerRows=transactions.map((member)=>{const payment=payments.find((item)=>item.memberId===member.memberId);return `<tr><td class="membername">${safe(member.memberName)}</td><td>${safe(member.memberId)}</td><td>${rupee(due)}</td><td>${payment?rupee(payment.amount):"—"}</td><td>${payment?badge("verified"):badge("pending")}</td></tr>`}).join("");
  $("ledgerTable").innerHTML=table(ledgerRows,["Member","ID","Due","Paid","Status"]);
  $("membersTable").innerHTML=table(transactions.map((member)=>{const paid=payments.some((payment)=>payment.memberId===member.memberId),initials=member.memberName.split(" ").map((part)=>part[0]).join("");return `<tr><td><span class="userpic" style="display:inline-grid;vertical-align:middle;margin-right:8px">${safe(initials)}</span><span class="membername">${safe(member.memberName)}</span></td><td>${safe(member.memberId)}</td><td>${rupee(due)}</td><td>${paid?badge("verified"):badge("pending")}</td><td>${paid?"On track":evidence.overdueMemberIds.includes(member.memberId)?"Overdue":"Awaiting payment"}</td></tr>`}).join(""),["Member","Member ID","Monthly due","Payment status","Payment health"]);
  $("memberTimeline").innerHTML=Array.from({length:evidence.group.tenureMonths},(_,index)=>`<div style="text-align:center"><span class="cell ${index===0&&paidIds.has("M-01")?"paid":""}" style="width:23px;height:23px;border-radius:50%"></span><small style="display:block;color:var(--muted);font-size:9px;margin-top:4px">${index+1}</small></div>`).join("");
  const statement=Array.from({length:evidence.group.tenureMonths},(_,index)=>`<tr><td>Month ${index+1}</td><td>${rupee(evidence.group.baseInstalment)}</td><td>${rupee(evidence.group.dividend)}</td><td>₹0</td><td>${index===11?rupee(evidence.group.prizeAmount):"—"}</td><td>${rupee(evidence.group.netInstalment)}</td></tr>`).join("");
  $("statementTable").innerHTML=table(statement,["Month","Instalment","Dividend","Late fee","Prize","Net due"]);
  $("auditTable").innerHTML=table(paymentRows(audit),["Member","Transaction ID","Amount","Decision","Evidence check","Timestamp"]);
  $("reportVerified").textContent=verified.size; $("reportReview").textContent=audit.filter((event)=>["review","pending"].includes(event.status)).length;
  $("reportReject").textContent=audit.filter((event)=>["mismatch","failed","duplicate"].includes(event.status)).length;
  $("reportRecorded").textContent=payments.length; $("reportBar").style.height=`${Math.max(2,percent)}%`;
}

$("file").addEventListener("change",(event)=>{const file=event.target.files[0];if(!file)return;currentFile=file;$("fileTitle").textContent=file.name;$("fileSub").textContent=`${(file.size/1024).toFixed(0)} KB · screenshot preview loaded; correct the fields before checking`;$ ("screenshotState").textContent=`Screenshot selected: ${file.name}`;if(file.type.startsWith("image/")){const url=URL.createObjectURL(file);$("drop").style.backgroundImage=`linear-gradient(90deg,#f9fbfc 0%,#f9fbfce8 65%,#f9fbfc55 100%),url("${url}")`;$ ("drop").style.backgroundSize="cover";$ ("drop").style.backgroundPosition="center";}});
["dragenter","dragover"].forEach((eventName)=>$("drop").addEventListener(eventName,(event)=>{event.preventDefault();$("drop").classList.add("over")}));
["dragleave","drop"].forEach((eventName)=>$("drop").addEventListener(eventName,(event)=>{event.preventDefault();$("drop").classList.remove("over")}));
$("drop").addEventListener("drop",(event)=>{const file=event.dataTransfer.files[0];if(file){const transfer=new DataTransfer();transfer.items.add(file);$("file").files=transfer.files;$("file").dispatchEvent(new Event("change"));}});

$("verify").addEventListener("click",async()=>{const button=$("verify");button.disabled=true;button.textContent="Checking independent evidence…";try{const response=await request("/api/verify",{method:"POST",body:JSON.stringify({fields:{utr:$("utr").value,amount:$("amount").value,date:$("date").value,receiver:$("receiver").value,memberId:$("member").value},fileName:currentFile?.name||""})});const result=response.result;state=response.state;$("result").className=`result show ${result.status}`;$("result").innerHTML=`<b>${({verified:"✓ Verified · added to group ledger",duplicate:"↻ Duplicate transaction reference",failed:"× Verification failed",mismatch:"! Payment mismatch",review:"! Needs more details"})[result.status]}</b>${safe(result.reason)}`;render();}catch(error){$("result").className="result show failed";$("result").innerHTML=`<b>Verification service unavailable</b>${safe(error.message)}`;}finally{button.disabled=false;button.innerHTML="Verify and update ledger &nbsp; →";}});
document.querySelectorAll(".filter").forEach((button)=>button.addEventListener("click",()=>{document.querySelectorAll(".filter").forEach((item)=>item.classList.remove("active"));button.classList.add("active");activeFilter=button.dataset.filter;render();}));
$("discount").addEventListener("input",()=>{const group=evidence?.group;if(!group)return;const discount=Math.max(0,Math.min(group.chitValue,Number($("discount").value)||0));const dividend=Math.max(0,discount-group.foremanCommission)/group.memberCount;$("dividendCalc").textContent=rupee(dividend);$("prizeCalc").textContent=rupee(group.chitValue-discount);$("netCalc").textContent=rupee(group.baseInstalment-dividend);});
$("exportCsv").addEventListener("click",()=>{const rows=[["Month","Instalment","Dividend","Late fee","Prize","Net due"],...Array.from({length:evidence.group.tenureMonths},(_,index)=>["Month "+(index+1),evidence.group.baseInstalment,evidence.group.dividend,0,index===11?evidence.group.prizeAmount:"",evidence.group.netInstalment])];const csv=rows.map((row)=>row.join(",")).join("\r\n");const link=document.createElement("a");link.href=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));link.download="chitmirror-statement.csv";link.click();URL.revokeObjectURL(link.href);});
$("role").addEventListener("change",()=>{if($("role").value==="Member view")showPage("mychit");else if($("role").value==="Foreman view")showPage("dashboard");else showPage("verify");});
async function reset(){try{state=await request("/api/reset",{method:"POST",body:"{}"});$("result").className="result";render();const toast=$("toast");toast.textContent="Demo ledger and audit trail reset";toast.className="toast show";setTimeout(()=>toast.className="toast",2200);}catch(error){const toast=$("toast");toast.textContent=`Reset failed: ${error.message}`;toast.className="toast show";setTimeout(()=>toast.className="toast",2600);}}
loadDemoData().catch((error)=>{console.error(error);document.querySelectorAll(".page").forEach((page)=>page.classList.remove("active"));const page=$("page-dashboard");page.classList.add("active");page.insertAdjacentHTML("afterbegin",'<p class="result show failed">Demo data could not be loaded. Run the FastAPI server and check the /data route.</p>');});


