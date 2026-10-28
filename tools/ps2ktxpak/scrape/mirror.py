"""Copy what one bucket holds that another lacks, in the cloud: the public packs from R2 to the B2
bucket the apps fall back to. Run by a container the Worker starts (`POST /mirror`), so the files never
cross a home connection. A file the destination already holds is never sent again: R2 and B2 share no
checksum, so rclone would otherwise compare modification times, which differ between the two copies, and
re-upload every file (on B2, also keeping the old copy as a billed version)."""
from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import signal
import subprocess
import threading
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ps2ktxpak scrape mirror")
    ap.add_argument("--src", default=os.environ.get("MIRROR_SRC", "r2:armsx2-textures/packs"))
    ap.add_argument("--dst", default=os.environ.get("MIRROR_DST", "b2:armsx2-textures/packs"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "0")), help="serve status here")
    a = ap.parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: os._exit(143))  # process 1 in a container; see job.main

    status = {"state": "running", "mode": "mirror", "src": a.src, "dst": a.dst, "started": time.time(),
              "progress": None, "errors": 0, "last_error": None}
    if a.port:
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(status).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        srv = http.server.ThreadingHTTPServer(("0.0.0.0", a.port), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    p = subprocess.Popen(["rclone", "copy", a.src, a.dst, "--ignore-existing", "--transfers", "16", "--stats", "60s",
                          "--stats-one-line", "--stats-log-level", "NOTICE", "--retries", "5"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    for line in p.stderr:
        line = line.strip()
        print(line, flush=True)
        if re.search(r"\d+%", line):
            status["progress"] = line
        elif "ERROR" in line:
            status["errors"] += 1
            status["last_error"] = line[-300:]
    status.update(state="finished" if p.wait() == 0 else "failed", exit=p.returncode, finished=time.time())
    print(f"mirror {status['state']}: exit {p.returncode}", flush=True)
    if a.port:  # keep answering the Worker until it stops the container
        while True:
            time.sleep(3600)
    return p.returncode
