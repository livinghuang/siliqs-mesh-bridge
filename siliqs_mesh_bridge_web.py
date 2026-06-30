#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Siliqs / Guinea Technology Corporation
"""
siliqs_mesh_bridge_web.py — a localhost control panel for the bridge.

Start/stop the bridge and watch its log from a browser, **no command line**. It
needs host OS access (serial ports / PTY / BLE / MQTT), so it is a tiny local HTTP
server (stdlib only — no extra deps) that spawns the verified `siliqs_mesh_bridge`
CLI as a subprocess and streams its output. Binds 127.0.0.1 by default.

  siliqs-mesh-bridge-web            # then open http://127.0.0.1:8765
"""
import argparse
import json
import subprocess
import sys
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import siliqs_mesh_bridge   # reuse the verified CLI (we spawn this file)

BRIDGE = siliqs_mesh_bridge.__file__


class Runner:
    """Owns the single bridge subprocess + a rolling log."""

    def __init__(self):
        self.proc = None
        self.argv = None
        self.log = deque(maxlen=400)
        self.lock = threading.Lock()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, cfg):
        with self.lock:
            if self.running():
                return False, "already running — stop it first"
            argv = self._build_argv(cfg)          # raises ValueError on bad config
            self.argv = argv
            self.log.clear()
            self.log.append("$ siliqs-mesh-bridge " + " ".join(argv))
            self.proc = subprocess.Popen(
                [sys.executable, "-u", BRIDGE, *argv],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            threading.Thread(target=self._pump, daemon=True).start()
            return True, "started"

    def _pump(self):
        try:
            for line in self.proc.stdout:
                self.log.append(line.rstrip("\n"))
        except Exception:
            pass
        self.log.append("— bridge process exited —")

    def stop(self):
        with self.lock:
            if not self.running():
                return False, "not running"
            self.proc.terminate()
            try:
                self.proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            return True, "stopped"

    @staticmethod
    def _build_argv(cfg):
        a = ["--verbose"]
        iface = cfg.get("iface", "usb")
        a += ["--iface", iface]
        if iface == "ble":
            if not cfg.get("ble"):
                raise ValueError("BLE device name/address required")
            a += ["--ble", cfg["ble"]]
        else:
            if not cfg.get("port"):
                raise ValueError("USB serial port required")
            a += ["--port", cfg["port"]]
        h = cfg.get("handler", "serial")
        a += ["--handler", h]
        if h == "serial":
            if not cfg.get("peer"):
                raise ValueError("peer node required (e.g. !7d51bdc4)")
            a += ["--peer", cfg["peer"]]
            if cfg.get("link"):
                a += ["--link", cfg["link"]]
            a += ["--mode", cfg.get("mode", "line"), "--mtu", str(int(cfg.get("mtu", 200)))]
        elif h == "mqtt":
            if not cfg.get("broker"):
                raise ValueError("MQTT broker host required")
            a += ["--broker", cfg["broker"],
                  "--broker-port", str(int(cfg.get("broker_port", 1883))),
                  "--channel", cfg.get("channel", "LongFast")]
        return a


runner = Runner()


def list_ports():
    try:
        from serial.tools import list_ports as lp
        return [{"device": p.device, "desc": p.description or ""} for p in lp.comports()]
    except Exception:
        return []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/ports":
            self._send(200, {"ports": list_ports()})
        elif self.path == "/api/state":
            self._send(200, {"running": runner.running(), "argv": runner.argv,
                             "log": list(runner.log)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            cfg = json.loads(raw or b"{}")
        except Exception:
            cfg = {}
        if self.path == "/api/start":
            try:
                ok, msg = runner.start(cfg)
                self._send(200, {"ok": ok, "msg": msg})
            except ValueError as e:
                self._send(400, {"ok": False, "msg": str(e)})
        elif self.path == "/api/stop":
            ok, msg = runner.stop()
            self._send(200, {"ok": ok, "msg": msg})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, *a):   # keep the console quiet
        pass


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>siliqs-mesh-bridge · control panel</title>
<style>
 :root{--bg:#14151a;--panel:#1d1f27;--panel2:#23262f;--bd:#2e3140;--tx:#e7e9ee;--mut:#9aa0ad;--ac:#67ea94;--acd:#3fbf6e;--dn:#ff6b6b}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
 header{display:flex;align-items:center;gap:12px;padding:14px 20px;background:var(--panel);border-bottom:1px solid var(--bd)}
 header b{font-size:16px} .dot{width:10px;height:10px;border-radius:50%;background:var(--mut)} .dot.on{background:var(--ac);box-shadow:0 0 8px var(--ac)}
 main{max-width:780px;margin:0 auto;padding:22px 20px}
 .card{background:var(--panel);border:1px solid var(--bd);border-radius:12px;padding:18px 20px;margin-bottom:18px}
 h2{margin:0 0 12px;font-size:15px} label{font-size:12px;color:var(--mut);display:block;margin-bottom:4px}
 .row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:12px} .field{display:flex;flex-direction:column;flex:1;min-width:160px}
 input,select{background:var(--panel2);color:var(--tx);border:1px solid var(--bd);border-radius:8px;padding:8px 10px;font:inherit}
 .seg{display:flex;gap:8px} .seg label{display:flex;align-items:center;gap:6px;color:var(--tx);background:var(--panel2);border:1px solid var(--bd);border-radius:8px;padding:8px 12px;cursor:pointer;margin:0}
 button{background:var(--panel2);color:var(--tx);border:1px solid var(--bd);border-radius:8px;padding:9px 16px;font:inherit;cursor:pointer}
 button.primary{background:var(--ac);color:#06210f;border-color:var(--ac);font-weight:600} button.danger{color:var(--dn);border-color:#5a2b2b}
 button:disabled{opacity:.45;cursor:not-allowed} .note{font-size:12px;color:var(--mut)}
 pre{background:#0e0f13;border:1px solid var(--bd);border-radius:8px;padding:12px;height:280px;overflow:auto;font:12px ui-monospace,monospace;white-space:pre-wrap;color:#cfd3da}
 .hide{display:none}
</style></head><body>
<header><span id="dot" class="dot"></span><b>siliqs-mesh-bridge</b><span class="note">control panel</span>
 <span style="flex:1"></span><span id="status" class="note">stopped</span></header>
<main>
 <div class="card">
  <h2>Transport (the node)</h2>
  <div class="seg" id="iface">
   <label><input type="radio" name="iface" value="usb" checked> USB</label>
   <label><input type="radio" name="iface" value="ble"> BLE</label></div>
  <div class="row" id="usbRow" style="margin-top:12px">
   <div class="field" style="flex:2"><label>Serial port</label><select id="port"></select></div>
   <div class="field" style="flex:0"><label>&nbsp;</label><button id="refresh" type="button">↻ refresh</button></div></div>
  <div class="row hide" id="bleRow" style="margin-top:12px">
   <div class="field"><label>BLE device name or address</label><input id="ble" placeholder="e.g. SQC485I"></div></div>
 </div>

 <div class="card">
  <h2>What to run</h2>
  <div class="seg" id="handler">
   <label><input type="radio" name="handler" value="serial" checked> Serial pipe</label>
   <label><input type="radio" name="handler" value="mqtt"> MQTT gateway</label></div>

  <div id="serialCfg" style="margin-top:12px">
   <div class="row">
    <div class="field"><label>Peer node (the other end)</label><input id="peer" placeholder="!7d51bdc4"></div>
    <div class="field"><label>Virtual port path (link)</label><input id="link" placeholder="/tmp/meshtty"></div></div>
   <div class="row">
    <div class="field"><label>Framing</label><select id="mode"><option value="line">line (per Enter)</option><option value="stream">stream (binary)</option></select></div>
    <div class="field"><label>Max bytes / packet</label><input id="mtu" type="number" value="50" min="1" max="233"></div></div>
   <p class="note">Run this on <b>both</b> hosts, each peer pointing at the other. Open the printed
    <code>/dev/pts/…</code> (or the link) with your serial software.</p>
  </div>

  <div id="mqttCfg" class="hide" style="margin-top:12px">
   <div class="row">
    <div class="field" style="flex:2"><label>Broker host</label><input id="broker" placeholder="192.168.0.9"></div>
    <div class="field"><label>Port</label><input id="brokerPort" type="number" value="1883"></div>
    <div class="field"><label>Channel</label><input id="channel" placeholder="LongFast"></div></div>
   <p class="note">Run on a gateway node (role CLIENT_MUTE). Forwards Modbus telemetry to MQTT.</p>
  </div>
 </div>

 <div class="card">
  <div class="row" style="align-items:center;margin:0">
   <button id="start" class="primary">Start</button>
   <button id="stop" class="danger" disabled>Stop</button>
   <span id="msg" class="note"></span></div>
  <h2 style="margin-top:16px">Log</h2>
  <pre id="log">—</pre>
 </div>
</main>
<script>
const $=id=>document.getElementById(id);
const val=id=>$(id).value.trim();
function ifaceVal(){return document.querySelector('input[name=iface]:checked').value}
function handlerVal(){return document.querySelector('input[name=handler]:checked').value}
function syncUI(){
 $('usbRow').classList.toggle('hide', ifaceVal()!=='usb');
 $('bleRow').classList.toggle('hide', ifaceVal()!=='ble');
 $('serialCfg').classList.toggle('hide', handlerVal()!=='serial');
 $('mqttCfg').classList.toggle('hide', handlerVal()!=='mqtt');
}
$('iface').onchange=syncUI; $('handler').onchange=syncUI;
async function loadPorts(){
 const r=await fetch('/api/ports'); const d=await r.json();
 const sel=$('port'); const cur=sel.value;
 sel.innerHTML=d.ports.map(p=>`<option value="${p.device}">${p.device} — ${p.desc}</option>`).join('')||'<option value="">(no serial ports)</option>';
 if([...sel.options].some(o=>o.value===cur)) sel.value=cur;
}
$('refresh').onclick=loadPorts;
function cfg(){
 const c={iface:ifaceVal(),handler:handlerVal()};
 if(c.iface==='usb') c.port=val('port'); else c.ble=val('ble');
 if(c.handler==='serial'){c.peer=val('peer');c.link=val('link');c.mode=val('mode');c.mtu=+val('mtu')||50;}
 else {c.broker=val('broker');c.broker_port=+val('brokerPort')||1883;c.channel=val('channel')||'LongFast';}
 return c;
}
$('start').onclick=async()=>{
 $('msg').textContent='starting…';
 const r=await fetch('/api/start',{method:'POST',body:JSON.stringify(cfg())});
 const d=await r.json(); $('msg').textContent=d.msg; $('msg').style.color=d.ok?'var(--mut)':'var(--dn)';
};
$('stop').onclick=async()=>{const r=await fetch('/api/stop',{method:'POST'});const d=await r.json();$('msg').textContent=d.msg;};
async function poll(){
 try{const r=await fetch('/api/state');const d=await r.json();
  $('dot').classList.toggle('on',d.running);
  $('status').textContent=d.running?'running':'stopped';
  $('start').disabled=d.running; $('stop').disabled=!d.running;
  const log=$('log'); const atBottom=log.scrollTop+log.clientHeight>=log.scrollHeight-20;
  log.textContent=(d.log||[]).join('\n')||'—';
  if(atBottom) log.scrollTop=log.scrollHeight;
 }catch(e){}
}
syncUI(); loadPorts(); poll(); setInterval(poll,1000);
</script></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="Local control panel for siliqs-mesh-bridge.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"siliqs-mesh-bridge control panel → http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runner.stop()


if __name__ == "__main__":
    main()
