"""OBS 로 자막 보내기: OBS '브라우저' 소스로 여는 작은 웹 서버.

- http://127.0.0.1:<포트>/ 를 OBS 브라우저 소스에 넣으면 배경이 투명한 자막만 보인다
- 앱은 말이 들리고 번역될 때마다 /events (SSE) 로 보내고, 페이지가 자막 창처럼 쌓고 흐리게 한다
- 모양(글자 크기·배경·사라지는 시간·쌓이는 말 수·원문 보기)은 자막 설정을 그대로 따른다
- 시청자가 보는 화면이라 상태 문구('준비 중…')와 번역 실패는 보내지 않는다
- 이 PC 에서만 열린다 (127.0.0.1). Qt 를 쓰지 않는다 — 앱(메인 스레드)은 show_* 만 부른다
"""

from __future__ import annotations

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .subtitle import MAX_SOURCE_CHARS, MAX_TRANSLATION_CHARS, clip

DEFAULT_PORT = 17321
KEEP = 8            # 새로 연결한 페이지(OBS 를 다시 켰을 때 등)에 다시 보내 줄 최근 말 수
PING_SEC = 15       # 말이 없어도 연결이 살아 있게
CFG_KEYS = ("subtitle_size", "subtitle_original", "subtitle_opacity", "subtitle_hide_sec", "subtitle_max_lines")


def url(port: int) -> str:
    # localhost 로 쓰면 IPv6(::1) 부터 시도해서 늦어진다. 서버는 127.0.0.1 에서만 듣는다
    return f"http://127.0.0.1:{port}/"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    # Windows 에서 SO_REUSEADDR 은 남이 쓰는 포트에도 같이 붙어 버린다 → 포트가 겹치면 바로 실패하게
    allow_reuse_address = False


class ObsServer:
    def __init__(self, cfg: dict, port: int = DEFAULT_PORT):
        self.port = port
        self._lock = threading.Lock()
        self._clients: list[queue.Queue] = []
        self._lines: dict[int, dict] = {}     # uid → {uid, source, text, kind, t}
        self._uid = 0
        self._cfg = {k: cfg[k] for k in CFG_KEYS}
        self._httpd: _Server | None = None

    # ---------- 켜기 / 끄기 ----------
    def start(self) -> None:
        """포트를 열고 듣기 시작한다. 포트를 못 열면 OSError."""
        self._httpd = _Server(("127.0.0.1", self.port), self._handler())
        self.port = self._httpd.server_address[1]      # 0 을 주면 빈 포트 (테스트용)
        threading.Thread(target=self._httpd.serve_forever, name="obs-server", daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            clients, self._clients = self._clients, []
        for q in clients:
            q.put(None)                 # 열려 있는 /events 연결을 끝낸다
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    @property
    def url(self) -> str:
        return url(self.port)

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    # ---------- 앱이 부르는 것 ----------
    def apply_cfg(self, cfg: dict) -> None:
        new = {k: cfg[k] for k in CFG_KEYS}
        with self._lock:
            if new == self._cfg:
                return
            self._cfg = new
        self._send({"type": "cfg", "cfg": new})

    def show_source(self, uid: int, text: str) -> None:
        if uid < self._uid:
            return
        self._uid = uid
        source = clip(text, MAX_SOURCE_CHARS)
        with self._lock:
            line = self._lines.get(uid)
            if line is None:
                line = self._lines[uid] = {"uid": uid, "source": source, "text": "", "kind": "pending"}
                for old in sorted(self._lines)[:-KEEP]:
                    del self._lines[old]
            else:
                line["source"] = source
            line["t"] = time.monotonic()
        self._send_line(line)

    def show_translation(self, uid: int, source: str, text: str) -> None:
        with self._lock:
            line = self._lines.get(uid)
            if line is None:
                return
            line.update(source=clip(source, MAX_SOURCE_CHARS), text=clip(text, MAX_TRANSLATION_CHARS),
                        kind="ok", t=time.monotonic())
        self._send_line(line)

    def show_failed(self, uid: int) -> None:
        """번역 실패는 시청자에게 보이지 않게 그 줄을 지운다."""
        with self._lock:
            if self._lines.pop(uid, None) is None:
                return
        self._send({"type": "drop", "uid": uid})

    # ---------- 보내기 ----------
    def _send_line(self, line: dict) -> None:
        self._send({"type": "line", "line": {k: v for k, v in line.items() if k != "t"}})

    def _send(self, event: dict) -> None:
        msg = json.dumps(event, ensure_ascii=False)
        with self._lock:
            for q in self._clients:
                q.put(msg)

    def _subscribe(self) -> queue.Queue:
        """새 페이지: 지금 모양과 최근 말들(얼마나 지났는지 포함)부터 보낸다."""
        q: queue.Queue = queue.Queue()
        now = time.monotonic()
        with self._lock:
            lines = [{**{k: v for k, v in l.items() if k != "t"}, "age": round(now - l["t"], 2)}
                     for _, l in sorted(self._lines.items())]
            q.put(json.dumps({"type": "reset", "cfg": self._cfg, "lines": lines}, ensure_ascii=False))
            self._clients.append(q)
        return q

    def _unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    body = PAGE.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/events":
                    self._events()
                else:
                    self.send_error(404)

            def _events(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                q = server._subscribe()
                try:
                    self.wfile.write(b"retry: 1000\n\n")     # 앱을 다시 켜면 1초 만에 다시 붙는다
                    while True:
                        try:
                            msg = q.get(timeout=PING_SEC)
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                            continue
                        if msg is None:
                            break
                        self.wfile.write(f"data: {msg}\n\n".encode("utf-8"))
                except OSError:
                    pass                    # OBS 가 소스를 닫음
                finally:
                    server._unsubscribe(q)

            def log_message(self, *_args):
                pass

        return Handler


# OBS 브라우저 소스가 여는 페이지. 배경은 투명, 자막은 아래 가운데에 쌓인다.
# 움직임은 자막 창(lt/subtitle.py)과 같은 규칙: 번역 전엔 원문, 번역이 오면 제자리에서 바뀜,
# 사라지는 시간 + 긴 문장은 15 자당 1초 더, 번역을 기다리는 말은 최대 60초.
PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>로컬 번역기 자막</title>
<style>
  :root { --size: 30px; --bg: 0.65; }
  html, body { margin: 0; height: 100%; overflow: hidden; background: transparent; }
  body { font-family: "Pretendard", "Malgun Gothic", sans-serif; }
  #wrap { position: fixed; left: 0; right: 0; bottom: 24px; display: flex; justify-content: center; }
  #box {
    max-width: min(1200px, 92vw); padding: 4px 28px 14px; border-radius: 12px; text-align: center;
    background: rgba(12, 12, 12, var(--bg)); transition: opacity .3s;
  }
  #box.empty { opacity: 0; }
  .line { display: grid; grid-template-rows: 0fr; opacity: 0; transition: grid-template-rows .3s ease, opacity .25s; }
  .line.shown { grid-template-rows: 1fr; opacity: 1; }
  .line.dying { opacity: 0; transition: grid-template-rows .35s ease .6s, opacity .6s; grid-template-rows: 0fr; }
  .line > div { overflow: hidden; min-height: 0; }
  .line > div > div { padding-top: 10px; }
  p { margin: 0; color: #fff; word-break: keep-all; overflow-wrap: anywhere; white-space: pre-wrap;
      text-shadow: 0 2px 0 rgba(0,0,0,.6), 1px 1px 0 rgba(0,0,0,.45), -1px 1px 0 rgba(0,0,0,.45); }
  p + p { margin-top: 4px; }
  .ok { font-size: var(--size); font-weight: 700; line-height: 1.3; }
  .pending { font-size: calc(var(--size) * .8); font-weight: 600; color: rgba(255,255,255,.6); line-height: 1.3; }
  .source { font-size: max(12px, calc(var(--size) * .55)); font-weight: 400; color: rgba(255,255,255,.75); line-height: 1.35; }
</style>
</head>
<body>
<div id="wrap"><div id="box" class="empty"></div></div>
<script>
const box = document.getElementById("box");
const PENDING_MAX_SEC = 60;
let cfg = { subtitle_size: 30, subtitle_original: true, subtitle_opacity: 65, subtitle_hide_sec: 8, subtitle_max_lines: 4 };
const lines = new Map();   // uid → { el, data, timer, dying }

function applyCfg() {
  document.documentElement.style.setProperty("--size", cfg.subtitle_size + "px");
  document.documentElement.style.setProperty("--bg", cfg.subtitle_opacity / 100);
  for (const l of lines.values()) render(l);
}

function blocks(d) {
  if (d.kind === "pending")   // 번역이 올 때까지는 원문을 크게
    return cfg.subtitle_original ? [[d.source, "source"], ["…", "pending"]] : [[d.source, "pending"]];
  return (cfg.subtitle_original && d.source ? [[d.source, "source"]] : []).concat([[d.text, "ok"]]);
}

function render(l) {
  const inner = l.el.firstChild.firstChild;
  inner.replaceChildren(...blocks(l.data).filter(b => b[0]).map(([text, cls]) => {
    const p = document.createElement("p");
    p.className = cls;
    p.textContent = text;
    return p;
  }));
}

function expireIn(l, age) {
  clearTimeout(l.timer);
  const hide = Number(cfg.subtitle_hide_sec);
  if (hide <= 0) return;
  const d = l.data;
  const sec = d.kind === "pending" ? PENDING_MAX_SEC : hide + Math.floor((d.text || d.source).length / 15);
  l.timer = setTimeout(() => kill(l), Math.max(0, sec - (age || 0)) * 1000);
}

function kill(l) {
  if (l.dying) return;
  l.dying = true;
  clearTimeout(l.timer);
  l.el.classList.add("dying");
  setTimeout(() => { if (l.dying) { l.el.remove(); if (lines.get(l.data.uid) === l) lines.delete(l.data.uid); sync(); } }, 1000);
  sync();
}

function trim() {   // 너무 많이 쌓이면 가장 오래된 말부터
  const alive = [...lines.values()].filter(l => !l.dying);
  const limit = Math.max(1, Number(cfg.subtitle_max_lines) || 4);
  while (alive.length > limit) kill(alive.shift());
}

function sync() {
  box.classList.toggle("empty", ![...lines.values()].some(l => !l.dying));
}

function upsert(d, age) {
  let l = lines.get(d.uid);
  if (l && l.dying) { l.el.remove(); lines.delete(d.uid); l = null; }
  if (!l) {
    const el = document.createElement("div");
    el.className = "line";
    el.innerHTML = "<div><div></div></div>";
    l = { el, data: d, timer: 0, dying: false };
    lines.set(d.uid, l);
    // 번호 순서대로 (늦게 온 번역이 아래로 가지 않게)
    const after = [...lines.values()].find(o => o !== l && o.data.uid > d.uid);
    box.insertBefore(el, after ? after.el : null);
  }
  l.data = d;
  render(l);
  if (!l.el.classList.contains("shown")) {
    void l.el.offsetHeight;     // 접힌 모양을 한 번 그린 뒤 펼쳐야 움직임이 보인다
    l.el.classList.add("shown");
  }
  expireIn(l, age);
  trim();
  sync();
}

function drop(uid) {
  const l = lines.get(uid);
  if (l) kill(l);
}

function reset(msg) {
  for (const l of lines.values()) { clearTimeout(l.timer); l.el.remove(); }
  lines.clear();
  cfg = msg.cfg;
  applyCfg();
  for (const d of msg.lines) upsert(d, d.age);
}

applyCfg();
const es = new EventSource("/events");
es.onmessage = e => {
  const msg = JSON.parse(e.data);
  if (msg.type === "reset") reset(msg);
  else if (msg.type === "cfg") { cfg = msg.cfg; applyCfg(); trim(); sync(); }
  else if (msg.type === "line") upsert(msg.line, 0);
  else if (msg.type === "drop") drop(msg.uid);
};
</script>
</body>
</html>
"""
