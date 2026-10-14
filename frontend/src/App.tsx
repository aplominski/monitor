import { createSignal, onCleanup, For, Show } from "solid-js";

type Stats = { cpu_pct: number; mem: any; disk: any; net: any; temps: { name: string; c: number }[]; load: number[]; uptime_s: number };
type Proc = { pid: number; name: string; mem_mb: number };
type Pt = { ts: number; cpu: number; mem: number; disk: number; temp: number };
type Key = "cpu" | "mem" | "disk" | "temp";
const META: Record<Key, { t: string; unit: string; max: number }> = {
  cpu: { t: "CPU", unit: "%", max: 100 }, mem: { t: "RAM", unit: "%", max: 100 },
  disk: { t: "DISK", unit: "%", max: 100 }, temp: { t: "TEMP", unit: "C", max: 100 },
};

function Bar(props: { v: number }) {
  return <div class="bar"><i style={{ width: Math.min(100, props.v) + "%" }} /></div>;
}
function Spark(props: { data: number[]; max?: number; big?: boolean }) {
  const pts = () => {
    const d = props.data.slice(-200), m = props.max || 100;
    return d.map((v, i) => `${(i / Math.max(1, d.length - 1)) * 100},${28 - (Math.min(v, m) / m) * 26}`).join(" ");
  };
  return <svg class={props.big ? "big" : "spark"} viewBox="0 0 100 30" preserveAspectRatio="none"><polyline points={pts()} /></svg>;
}
const fmtUp = (s: number) => `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
const fmtT = (ts: number) => new Date(ts * 1000).toLocaleString("en-GB", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });

export default function App() {
  const [st, setSt] = createSignal<Stats | null>(null);
  const [ps, setPs] = createSignal<Proc[]>([]);
  const [hi, setHi] = createSignal<Pt[]>([]);
  const [sel, setSel] = createSignal<Key | null>(null);
  const tick = async () => {
    try {
      setSt(await (await fetch("/api/stats")).json());
      setPs(await (await fetch("/api/processes")).json());
    } catch {}
  };
  const hist = async () => {
    try { setHi(await (await fetch("/api/history?hours=24")).json()); } catch {}
  };
  tick(); hist();
  const id = setInterval(tick, 2000);
  const id2 = setInterval(hist, 60000);
  const esc = (e: KeyboardEvent) => e.key === "Escape" && setSel(null);
  addEventListener("keydown", esc);
  onCleanup(() => { clearInterval(id); clearInterval(id2); removeEventListener("keydown", esc); });
  const col = (k: Key) => hi().map(r => Number(r[k]) || 0);
  const stat = (k: Key) => {
    const d = col(k);
    if (!d.length) return { min: 0, max: 0, avg: 0, last: 0 };
    return { min: Math.min(...d), max: Math.max(...d), avg: d.reduce((a, b) => a + b, 0) / d.length, last: d[d.length - 1] };
  };
  return (
    <main>
      <header><b>monitor</b><span>:8080 · log 15m · {hi().length} pkt/24h</span></header>
      <Show when={st()} fallback={<p class="loading">connecting…</p>}>
        <div class="grid">
          {(["cpu", "mem", "disk", "temp"] as Key[]).map(k => (
            <section class="card click" onClick={() => setSel(k)}>
              <h2>{META[k].t}{k === "cpu" ? ` ${st()!.cpu_pct}%` : k === "mem" ? ` ${st()!.mem.pct}%` : k === "disk" ? ` ${st()!.disk.pct}%` : ""}</h2>
              {k === "cpu" && <><Bar v={st()!.cpu_pct} /><Spark data={col("cpu")} /><small>load {st()!.load.join(" / ")}</small></>}
              {k === "mem" && <><Bar v={st()!.mem.pct} /><Spark data={col("mem")} /><small>{st()!.mem.used_mb} / {st()!.mem.total_mb} MB</small></>}
              {k === "disk" && <><Bar v={st()!.disk.pct} /><Spark data={col("disk")} /><small>{st()!.disk.used_gb} / {st()!.disk.total_gb} GB</small></>}
              {k === "temp" && <><Spark data={col("temp")} /><For each={st()!.temps.slice(0, 4)}>{t => <div class="trow"><span>{t.name}</span><b>{t.c}C</b></div>}</For></>}
            </section>
          ))}
          <section class="card">
            <h2>NET / UPTIME</h2>
            <small>down {st()!.net.rx_kbs} kB/s · up {st()!.net.tx_kbs} kB/s</small>
            <small>up {fmtUp(st()!.uptime_s)}</small>
          </section>
        </div>
        <section class="card">
          <h2>TOP PROCESSES</h2>
          <table><tbody>
            <For each={ps()}>{p => <tr><td>{p.pid}</td><td>{p.name}</td><td>{p.mem_mb} MB</td></tr>}</For>
          </tbody></table>
        </section>
      </Show>
      <Show when={sel()}>
        <div class="overlay" onClick={() => setSel(null)}>
          <div class="sheet" onClick={e => e.stopPropagation()}>
            <header><b>{META[sel()!].t} / 24h</b><button onClick={() => setSel(null)}>x</button></header>
            <Spark data={col(sel()!)} max={META[sel()!].max} big />
            <div class="stats">
              <span>min <b>{stat(sel()!).min.toFixed(1)}{META[sel()!].unit}</b></span>
              <span>avg <b>{stat(sel()!).avg.toFixed(1)}{META[sel()!].unit}</b></span>
              <span>max <b>{stat(sel()!).max.toFixed(1)}{META[sel()!].unit}</b></span>
              <span>samples <b>{col(sel()!).length}</b></span>
            </div>
            <small>{hi().length ? `${fmtT(hi()[0].ts)} – ${fmtT(hi()[hi().length - 1].ts)}` : "no data yet (logged every 15m)"}</small>
          </div>
        </div>
      </Show>
    </main>
  );
}
