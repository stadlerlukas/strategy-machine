"""Loopback-only application server. Not designed for remote/public deployment."""
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs

from .application import Application,blank_setup


def create_server(root,port=8877):
    app=Application(root)
    token=secrets.token_urlsafe(32)
    lock=threading.RLock()
    static=Path(__file__).parent/"web"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,format,*args):
            # Do not log request bodies, strategy text, secrets or URLs with input.
            return

        def allowed_host(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}",f"localhost:{self.server.server_port}")

        def send(self,code,body,content_type="application/json; charset=utf-8"):
            if isinstance(body,(dict,list)):
                body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
            elif isinstance(body,str):
                body=body.encode()
            self.send_response(code)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(body)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403,{"error":"Invalid local host"})
            url=urlsplit(self.path)
            q=parse_qs(url.query)
            try:
                with lock:
                    if url.path=="/":
                        text=(static/"index.html").read_text(encoding="utf-8").replace("__CSRF_TOKEN__",token)
                        return self.send(200,text,"text/html; charset=utf-8")
                    if url.path in ("/app.js","/style.css"):
                        kind="application/javascript" if url.path.endswith(".js") else "text/css"
                        return self.send(200,(static/url.path[1:]).read_bytes(),kind+"; charset=utf-8")
                    if url.path=="/api/cases":
                        return self.send(200,{"cases":app.cases(),"blank_setup":blank_setup()})
                    if url.path=="/api/state":
                        return self.send(200,app.state(q.get("case",[""])[0]))
                    if url.path=="/download":
                        name=q.get("file",[""])[0]
                        allowed={"report.html","evidence.json","strategy.spec.json","strategy.spec.draft.json","trials.csv","performance-note.txt","adverse-performance-note-template.txt"}
                        if name not in allowed:
                            return self.send(403,{"error":"That artifact is not available through this route"})
                        p=app.case_path(q.get("case",[""])[0])/name
                        kind="text/html" if name.endswith("html") else ("application/json" if name.endswith("json") else "text/plain")
                        if name=="report.html":
                            from urllib.parse import urlencode
                            text=p.read_text(encoding="utf-8")
                            for linked in ("trials.csv","evidence.json"):
                                text=text.replace('href="'+linked+'"','href="/download?'+urlencode({"case":q["case"][0],"file":linked})+'"')
                            return self.send(200,text,"text/html; charset=utf-8")
                        return self.send(200,p.read_bytes(),kind+"; charset=utf-8")
                return self.send(404,{"error":"Not found"})
            except (ValueError,OSError,KeyError) as exc:
                return self.send(400,{"error":str(exc)})

        def do_POST(self):
            origin=self.headers.get("Origin")
            origins={f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"}
            if not self.allowed_host() or self.headers.get("X-CSRF-Token")!=token or (origin and origin not in origins):
                return self.send(403,{"error":"Invalid local request token or origin"})
            if self.path!="/api/action":
                return self.send(404,{"error":"Not found"})
            try:
                length=int(self.headers.get("Content-Length","0"))
                if not 0<length<=27_000_000:
                    return self.send(413,{"error":"Request body is empty or exceeds 27 MB"})
                if not self.headers.get("Content-Type","").startswith("application/json"):
                    return self.send(415,{"error":"Send JSON"})
                request=json.loads(self.rfile.read(length))
                with lock:
                    result=app.action(request["case"],request["action"],request.get("args",{}))
                return self.send(200,{"result":result})
            except Exception as exc:
                # A failed action remains in its domain ledger when evaluation began.
                return self.send(400,{"error":str(exc),"type":type(exc).__name__})

    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.daemon_threads=True
    server.app=app
    server.csrf_token=token
    return server


def serve(root,port=8877,open_browser=True):
    server=create_server(root,port)
    url=f"http://127.0.0.1:{server.server_port}"
    print(f"Strategy Machine is running at {url}\nCases: {Path(root).resolve()}\nPress Ctrl+C to stop.",flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
