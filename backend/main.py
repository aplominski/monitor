import http.client as httpclient
import json
import os
import socket
import threading
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")
LOG = os.path.join(BASE, "metrics.jsonl")
INTERVAL = 900

_prev_cpu = None
_prev_net = None

def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return ""

def cpu_pct():
    global _prev_cpu
    line = _read("/proc/stat").splitlines()
    if not line:
        return 0.0
    p = list(map(int, line[0].split()[1:8]))
    idle, total = p[3], sum(p)
    if _prev_cpu:
        pi, pt = _prev_cpu
        d = total - pt or 1
        v = round(100 * (1 - (idle - pi) / d), 1)
    else:
        v = 0.0
    _prev_cpu = (idle, total)
    return v

def mem():
    m = {}
    for ln in _read("/proc/meminfo").splitlines():
        k, _, v = ln.partition(":")
        m[k] = int(v.split()[0])
    total = m.get("MemTotal", 1)
    avail = m.get("MemAvailable", m.get("MemFree", 0))
    return {"total_mb": total // 1024, "used_mb": (total - avail) // 1024,
            "pct": round(100 * (total - avail) / total, 1)}

def disk():
    st = os.statvfs("/")
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    return {"total_gb": round(total / 1e9, 1), "used_gb": round((total - free) / 1e9, 1),
            "pct": round(100 * (total - free) / total, 1)}

def net():
    global _prev_net
    rx = tx = 0
    for ln in _read("/proc/net/dev").splitlines()[2:]:
        p = ln.split()
        if p[0].rstrip(":") == "lo":
            continue
        rx += int(p[1]); tx += int(p[9])
    now = time.time()
    out = {"rx_kb": rx // 1024, "tx_kb": tx // 1024, "rx_kbs": 0.0, "tx_kbs": 0.0}
    if _prev_net:
        prx, ptx, pt = _prev_net
        dt = now - pt or 1
        out["rx_kbs"] = round((rx - prx) / 1024 / dt, 1)
        out["tx_kbs"] = round((tx - ptx) / 1024 / dt, 1)
    _prev_net = (rx, tx, now)
    return out

def temps():
    out = []
    for zone in sorted(os.listdir("/sys/class/thermal") if os.path.isdir("/sys/class/thermal") else []):
        if not zone.startswith("thermal_zone"):
            continue
        base = f"/sys/class/thermal/{zone}"
        try:
            c = int(_read(f"{base}/temp").strip()) / 1000
            out.append({"name": _read(f"{base}/type").strip() or zone, "c": round(c, 1)})
        except ValueError:
            continue
    if os.path.isdir("/sys/class/hwmon"):
        for h in sorted(os.listdir("/sys/class/hwmon")):
            base = f"/sys/class/hwmon/{h}"
            chip = _read(f"{base}/name").strip()
            for f in sorted(os.listdir(base)):
                if f.startswith("temp") and f.endswith("_input"):
                    label = _read(f"{base}/{f[:-6]}_label").strip() or f[:-6]
                    try:
                        c = int(_read(f"{base}/{f}").strip()) / 1000
                    except ValueError:
                        continue
                    if c <= 0 or c > 150:
                        continue
                    out.append({"name": f"{chip} {label}".strip(), "c": round(c, 1)})
    return out[:12]

def procs(limit=12):
    rows = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/stat") as f:
                s = f.read().rsplit(")", 1)[1].split()
            with open(f"/proc/{pid}/status") as f:
                st = f.read()
            rss = int(next(l for l in st.splitlines() if l.startswith("VmRSS")).split()[1]) // 1024
            rows.append({"pid": int(pid), "name": open(f"/proc/{pid}/comm").read().strip(),
                         "cpu_t": int(s[11]) + int(s[12]), "mem_mb": rss})
        except (OSError, StopIteration, IndexError):
            continue
    rows.sort(key=lambda r: r["cpu_t"], reverse=True)
    return [{k: v for k, v in r.items() if k != "cpu_t"} for r in rows[:limit]]

app = FastAPI(title="monitor")

def snapshot():
    up = float(_read("/proc/uptime").split()[0] or 0)
    m, d = mem(), disk()
    return {"ts": int(time.time()), "cpu": cpu_pct(), "mem": m["pct"],
            "disk": d["pct"], "uptime_s": int(up),
            "temp": max([t["c"] for t in temps()] or [0])}

def logger():
    while True:
        try:
            with open(LOG, "a") as f:
                f.write(json.dumps(snapshot()) + "\n")
        except OSError:
            pass
        time.sleep(INTERVAL)

threading.Thread(target=logger, daemon=True).start()

@app.get("/api/history")
def history(hours: int = 24):
    cutoff = time.time() - hours * 3600
    rows = []
    try:
        with open(LOG) as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if r.get("ts", 0) >= cutoff:
                    rows.append(r)
    except OSError:
        pass
    return rows[-400:]

@app.get("/api/stats")
def stats():
    up = float(_read("/proc/uptime").split()[0] or 0)
    return {"cpu_pct": cpu_pct(), "mem": mem(), "disk": disk(), "net": net(), "temps": temps(),
            "load": [round(x, 2) for x in os.getloadavg()], "uptime_s": int(up)}

def check_port(host, port, use_http=False, timeout=2.0):
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        ms = round((time.time() - t0) * 1000, 1)
        code = None
        if use_http:
            try:
                c = httpclient.HTTPConnection(host, port, timeout=timeout)
                c.request("GET", "/")
                code = c.getresponse().status
                c.close()
            except OSError:
                pass
        return {"open": True, "ms": ms, "code": code}
    except OSError:
        return {"open": False, "ms": None, "code": None}

PORTS_FILE = os.path.join(BASE, "ports.jsonl")

def load_ports():
    out = []
    try:
        with open(PORTS_FILE) as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        pass
    if not out:
        out = [
            {"name": "SSH", "host": "127.0.0.1", "port": 22},
            {"name": "HTTP", "host": "127.0.0.1", "port": 80, "http": True},
            {"name": "APP", "host": "127.0.0.1", "port": 8080, "http": True},
        ]
    return out

def save_ports(ports):
    with open(PORTS_FILE, "w") as f:
        for p in ports:
            f.write(json.dumps(p) + "\n")

@app.get("/api/ports")
def ports():
    return [{**p, **check_port(p["host"], p["port"], p.get("http", False))} for p in load_ports()]

@app.post("/api/ports")
def add_port(p: dict):
    ports = load_ports()
    ports.append({"name": str(p.get("name", "SVC"))[:24], "host": str(p.get("host", "127.0.0.1"))[:64],
                  "port": max(1, min(65535, int(p.get("port", 80)))), "http": bool(p.get("http", False))})
    save_ports(ports)
    return ports

@app.delete("/api/ports/{idx}")
def del_port(idx: int):
    ports = load_ports()
    if 0 <= idx < len(ports):
        ports.pop(idx)
        save_ports(ports)
    return ports

@app.get("/api/processes")
def processes():
    return procs()

if os.path.isdir(STATIC):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    @app.head("/{path:path}", include_in_schema=False)
    def spa(path: str):
        fp = os.path.join(STATIC, path)
        if path and os.path.isfile(fp):
            return FileResponse(fp)
        return FileResponse(os.path.join(STATIC, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
