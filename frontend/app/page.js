"use client";

import { useCallback, useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

async function api(path, method = "GET", body) {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
}

const C = {
  panel: { background: "#171a21", border: "1px solid #2a2f3a", borderRadius: 8, padding: 14 },
  btn: { background: "#2a2f3a", color: "#e6e6e6", border: "1px solid #3a4150", borderRadius: 6, padding: "5px 10px", cursor: "pointer", marginRight: 6, fontSize: 12 },
  input: { background: "#0f1115", color: "#e6e6e6", border: "1px solid #3a4150", borderRadius: 6, padding: "5px 8px", fontSize: 12 },
  badge: (s) => ({ padding: "2px 8px", borderRadius: 10, fontSize: 11, background: { running: "#1f4d2b", paused: "#5a4a1f", completed: "#1f3a5a", terminated: "#5a1f1f" }[s] || "#333", color: "#fff" }),
};

const KIND_COLORS = {
  action: "#7fd1b9", event: "#9fb4d8", summary: "#e0c068", instruction: "#c79ad8",
  wake_decision: "#666", lifecycle: "#d89a9a", llm: "#9ad8c7", fallback: "#d8b89a",
};

export default function Home() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [log, setLog] = useState([]);
  const [includeDebug, setIncludeDebug] = useState(false);
  const [eventTypes, setEventTypes] = useState([]);
  const [orderId, setOrderId] = useState("ORD-" + Math.floor(Math.random() * 9000 + 1000));
  const [wake, setWake] = useState(5);
  const [maxAge, setMaxAge] = useState(3600);
  const [startInstr, setStartInstr] = useState("");
  const [evType, setEvType] = useState("order_created");
  const [evText, setEvText] = useState("");
  const [instr, setInstr] = useState("");
  const [err, setErr] = useState("");
  const [offline, setOffline] = useState(false);

  const guard = (fn) => async (...a) => { try { setErr(""); await fn(...a); } catch (e) { setErr(String(e.message || e)); } };

  // Auto-dismiss the notice after a few seconds (also manually dismissable).
  useEffect(() => { if (!err) return; const t = setTimeout(() => setErr(""), 8000); return () => clearTimeout(t); }, [err]);

  // Polling refreshers must NEVER throw: a transient API blip (e.g. SG/IP change) flips an
  // "offline" flag instead of crashing the page with an unhandled rejection (which blanked it).
  const refreshRuns = useCallback(async () => {
    try { setRuns((await api("/runs")).runs); setOffline(false); }
    catch { setOffline(true); }
  }, []);
  const refreshSelected = useCallback(async () => {
    if (!selected) return;
    try {
      setDetail(await api(`/runs/${selected}`));
      setLog((await api(`/runs/${selected}/log?include_debug=${includeDebug}`)).entries);
      setOffline(false);
    } catch { setOffline(true); }
  }, [selected, includeDebug]);

  useEffect(() => { api("/events/types").then((d) => setEventTypes(d.event_types)).catch(() => {}); }, []);
  useEffect(() => {
    refreshRuns();
    const t = setInterval(() => { refreshRuns(); refreshSelected(); }, 2000);
    return () => clearInterval(t);
  }, [refreshRuns, refreshSelected]);
  useEffect(() => { refreshSelected(); }, [refreshSelected]);

  const startRun = guard(async () => {
    const body = { order_id: orderId, wake_interval_s: Number(wake), max_run_age_s: Number(maxAge) };
    if (startInstr.trim()) body.instructions = [startInstr.trim()];
    const r = await api("/runs", "POST", body);
    setOrderId("ORD-" + Math.floor(Math.random() * 9000 + 1000));
    setStartInstr("");
    setSelected(r.run_id);
    await refreshRuns();
  });
  const injectEvent = guard(async () => {
    const body = { type: evType, payload: {} };
    if (evType === "customer_message_received" && evText.trim()) body.payload.text = evText.trim();
    await api(`/runs/${selected}/events`, "POST", body);
    setEvText("");
    await refreshSelected();
  });
  const addInstruction = guard(async () => {
    if (!instr.trim()) return;
    await api(`/runs/${selected}/instructions`, "POST", { text: instr.trim() });
    setInstr("");
    await refreshSelected();
  });
  const lifecycle = guard(async (action) => {
    if (action === "terminate") await api(`/runs/${selected}/terminate`, "POST", { reason: "stopped from UI" });
    else await api(`/runs/${selected}/${action}`, "POST", {});
    await refreshSelected(); await refreshRuns();
  });

  return (
    <div style={{ padding: 20, maxWidth: 1200, margin: "0 auto" }}>
      <h1 style={{ fontSize: 20 }}>OrderPilot — Order Supervisor</h1>
      <p style={{ color: "#888", fontSize: 12, marginTop: -8 }}>
        Temporal-backed · API: {API}
        {offline && <span style={{ color: "#e7c46a" }}> · reconnecting…</span>}
      </p>
      {err && (
        <div role="alert" style={{ background: "#2a2418", border: "1px solid #6b5524", color: "#e7c46a",
          borderRadius: 8, padding: "10px 12px", marginBottom: 12, display: "flex",
          justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
          <span><b>⚠ Notice — </b>{err}</span>
          <button onClick={() => setErr("")} aria-label="dismiss" style={{ background: "transparent",
            border: "none", color: "#e7c46a", cursor: "pointer", fontSize: 16, lineHeight: 1 }}>×</button>
        </div>
      )}

      {/* Start a run */}
      <div style={{ ...C.panel, marginBottom: 16 }}>
        <b>Start a run</b>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "center" }}>
          <label>order <input style={C.input} value={orderId} onChange={(e) => setOrderId(e.target.value)} /></label>
          <label>wake(s) <input style={{ ...C.input, width: 60 }} type="number" value={wake} onChange={(e) => setWake(e.target.value)} /></label>
          <label>maxAge(s) <input style={{ ...C.input, width: 80 }} type="number" value={maxAge} onChange={(e) => setMaxAge(e.target.value)} /></label>
          <input style={{ ...C.input, flex: 1, minWidth: 220 }} placeholder="optional instruction (e.g. escalate delays immediately)" value={startInstr} onChange={(e) => setStartInstr(e.target.value)} />
          <button style={C.btn} onClick={startRun}>Start</button>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 16 }}>
        {/* Runs list */}
        <div style={C.panel}>
          <b>Runs ({runs.length})</b>
          <div style={{ marginTop: 8 }}>
            {runs.map((r) => (
              <div key={r.run_id} onClick={() => setSelected(r.run_id)}
                style={{ padding: 8, borderRadius: 6, marginBottom: 6, cursor: "pointer",
                  background: selected === r.run_id ? "#222838" : "transparent", border: "1px solid #232833" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span>{r.order_id}</span><span style={C.badge(r.status)}>{r.status}</span>
                </div>
                <div style={{ color: "#777", fontSize: 11 }}>{r.run_id}</div>
              </div>
            ))}
            {runs.length === 0 && <div style={{ color: "#777", fontSize: 12 }}>no runs yet</div>}
          </div>
        </div>

        {/* Selected run */}
        <div style={C.panel}>
          {!selected && <div style={{ color: "#777" }}>Select a run to inspect.</div>}
          {selected && detail && (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b>{detail.run.order_id}</b>
                <span style={C.badge(detail.run.status)}>{detail.run.status}</span>
              </div>
              <div style={{ color: "#888", fontSize: 11, marginBottom: 8 }}>
                {detail.run.run_id} · wake {detail.run.wake_interval_s}s · maxAge {detail.run.max_run_age_s}s
                {detail.live?.paused ? " · PAUSED" : ""}
              </div>

              {/* Lifecycle controls */}
              <div style={{ marginBottom: 10 }}>
                <button style={C.btn} onClick={() => lifecycle("pause")}>Pause</button>
                <button style={C.btn} onClick={() => lifecycle("resume")}>Resume</button>
                <button style={C.btn} onClick={() => lifecycle("interrupt")}>Interrupt</button>
                <button style={{ ...C.btn, borderColor: "#a33" }} onClick={() => lifecycle("terminate")}>Terminate</button>
              </div>

              {/* Inject event */}
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8, alignItems: "center" }}>
                <select style={C.input} value={evType} onChange={(e) => setEvType(e.target.value)}>
                  {eventTypes.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
                {evType === "customer_message_received" &&
                  <input style={{ ...C.input, flex: 1, minWidth: 180 }} placeholder="message text" value={evText} onChange={(e) => setEvText(e.target.value)} />}
                <button style={C.btn} onClick={injectEvent}>Inject event</button>
              </div>

              {/* Add instruction */}
              <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
                <input style={{ ...C.input, flex: 1 }} placeholder="add instruction to live run" value={instr} onChange={(e) => setInstr(e.target.value)} />
                <button style={C.btn} onClick={addInstruction}>Add instruction</button>
              </div>

              {/* Live state */}
              {detail.live?.state && Object.keys(detail.live.state).length > 0 && (
                <div style={{ fontSize: 11, color: "#9ab", marginBottom: 8 }}>
                  state: {JSON.stringify(detail.live.state)}
                </div>
              )}

              {/* Activity log */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b>Activity log ({log.length})</b>
                <label style={{ fontSize: 11, color: "#aaa" }}>
                  <input type="checkbox" checked={includeDebug} onChange={(e) => setIncludeDebug(e.target.checked)} /> show debug (no-op wakes)
                </label>
              </div>
              <div style={{ marginTop: 6, maxHeight: 420, overflowY: "auto", fontSize: 12 }}>
                {log.map((e) => (
                  <div key={e.id} style={{ padding: "4px 0", borderBottom: "1px solid #20242e", opacity: e.visibility === "debug" ? 0.55 : 1 }}>
                    <span style={{ color: KIND_COLORS[e.kind] || "#aaa" }}>
                      {e.action || e.kind}
                    </span>
                    {e.trigger && <span style={{ color: "#566", marginLeft: 6 }}>[{e.trigger}]</span>}
                    <span style={{ marginLeft: 6 }}>{e.message}</span>
                  </div>
                ))}
                {log.length === 0 && <div style={{ color: "#777" }}>no entries</div>}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
