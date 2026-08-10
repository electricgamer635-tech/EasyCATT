import argparse
import mimetypes
import json
import os
import re
import subprocess
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "catt-builder.html")
MAIN = os.path.join(HERE, "main.py")

BOOL_FLAGS = ("template", "onehot", "categories", "expand", "map",
              "days", "age", "force", "counts")
LOG_LEVELS = ("debug", "info", "warning", "error", "critical")

RE_GENE = re.compile(r"^[A-Za-z0-9._@-]+(,[A-Za-z0-9._@-]+)*$")
RE_VARIANT = re.compile(r"^[0-9]+(,[0-9]+)*$")
RE_COLUMNS = re.compile(r"^[A-Za-z0-9 ._-]+(,[A-Za-z0-9 ._-]+)*$")
RE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
RE_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")

BATCH_TXT_SOURCES = ("clinvar-submission-summary,clinvar-variant-summary,vrs,"
                     "gencc-submissions,clingen-gene-disease,"
                     "clingen-consensus-assertions-adult,"
                     "clingen-consensus-assertions-pediatric,clingen-dosage,"
                     "clingen-overall-scores-adult,"
                     "clingen-overall-scores-pediatric")
BATCH_CSV_SOURCES = ("clinvar-submission-summary,clinvar-variant-summary,"
                     "gencc-submissions,clingen-dosage,clingen-gene-disease,vrs")


class NoNoRequest(Exception):
    """The browser sent something that failed validation"""

class Runner:
    def __init__(self):
        self.lock = threading.Lock()
        self.lines = []
        self.running = False
        self.exit_code = None
        self.proc = None
        self.cancel = False

    def emit(self, text):
        with self.lock:
            self.lines.append(text)

    def snapshot(self, since):
        with self.lock:
            return {
                "lines": self.lines[since:],
                "next": len(self.lines),
                "running": self.running,
                "exit": self.exit_code,
            }

    def start(self, jobs, label):
        with self.lock:
            if self.running:
                raise NoNoRequest("A run is already in progress.")
            self.lines = []
            self.running = True
            self.exit_code = None
            self.cancel = False
        threading.Thread(target=self._work, args=(jobs, label), daemon=True).start()

    def stop(self):
        with self.lock:
            self.cancel = True
            proc = self.proc
        if proc and proc.poll() is None:
            proc.terminate()

    def _work(self, jobs, label):
        code = 0
        failed = []
        started = time.time()
        self.emit("$ " + label)
        self.emit("")
        try:
            for index, (argv, note) in enumerate(jobs, start=1):
                with self.lock:
                    if self.cancel:
                        self.emit("Stopped before finishing.")
                        code = 130
                        break
                if note:
                    self.emit("--- %s (%d of %d) ---" % (note, index, len(jobs)))
                code = self._one(argv)
                if code == 0:
                    continue
                if index == 1:
                    # prolly a setup problem
                    self.emit("")
                    self.emit("The first item failed, so the rest were skipped.")
                    break
                failed.append(note or str(index))
                self.emit("")
                self.emit("That one failed. Carrying on with the rest.")
                code = 0
        except Exception as exc: # noqa: BLE001
            self.emit("Runner error: %s" % exc)
            code = 1
        elapsed = time.time() - started
        self.emit("")

        if code == 0 and failed:
            self.emit("Finished in %s, but %d item(s) failed: %s"
                      % (_duration(elapsed), len(failed), ", ".join(failed[:10])))
        elif code == 0:
            self.emit("Finished in %s." % _duration(elapsed))
        elif code == 130:
            self.emit("Cancelled after %s." % _duration(elapsed))
        else:
            self.emit("Stopped with exit code %d after %s." % (code, _duration(elapsed)))
        with self.lock:
            self.running = False
            self.exit_code = code
            self.proc = None

    def _one(self, argv):
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(
            argv, cwd=HERE, env=env, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, errors="replace",
        )
        with self.lock:
            self.proc = proc
        for line in proc.stdout:
            self.emit(line.rstrip("\n"))
        proc.stdout.close()
        return proc.wait()


def _duration(seconds):
    if seconds < 60:
        return "%.1f seconds" % seconds
    return "%d min %d sec" % (int(seconds // 60), int(seconds % 60))


BLADERUNNER = Runner() # elite ball knowledge

def known_sources():
    root = os.path.join(HERE, "sources")
    if not os.path.isdir(root):
        return []
    found = []
    for name in sorted(os.listdir(root)):
        if os.path.isfile(os.path.join(root, name, "config.yml")):
            found.append(name)
    return found


def source_status():
    """Report which sources already have their data file downloaded."""
    import yaml

    out = []
    for name in known_sources():
        path = os.path.join(HERE, "sources", name)
        present = False
        try:
            with open(os.path.join(path, "config.yml"), encoding="utf-8") as handle:
                doc = yaml.safe_load(handle)
            entry = doc[0] if isinstance(doc, list) else doc
            filename = (entry or {}).get("file")
            if filename:
                present = os.path.isfile(os.path.join(path, str(filename)))
        except Exception: # noqa: BLE001
            present = False
        out.append({"name": name, "downloaded": present})
    return out


def _text(spec, key, pattern, label, limit=200):
    value = str(spec.get(key, "") or "").strip()
    if not value:
        return ""
    if len(value) > limit:
        raise NoNoRequest("%s is too long." % label)
    if pattern and not pattern.match(value):
        raise NoNoRequest("%s contains characters that aren't allowed here." % label)
    return value


def build_single(spec):
    argv = [sys.executable, MAIN]
    shown = ["python", "main.py"]

    level = str(spec.get("loglevel", "") or "").strip().lower()
    if level:
        if level not in LOG_LEVELS:
            raise NoNoRequest("Unrecognised log level.")
        argv.append("--loglevel=" + level)
        shown.append("--loglevel=" + level)

    for flag in BOOL_FLAGS:
        if spec.get(flag):
            argv.append("--" + flag)
            shown.append("--" + flag)

    na = str(spec.get("na-value", "") or "")
    if na:
        if len(na) > 64 or "\n" in na or "\r" in na:
            raise NoNoRequest("The missing-value replacement is too long.")
        argv.append("--na-value=" + na)
        shown.append('--na-value="%s"' % na)

    chosen = spec.get("sources") or []
    if not isinstance(chosen, list):
        raise NoNoRequest("Sources must be a list.")
    valid = set(known_sources())
    for name in chosen:
        if name not in valid:
            raise NoNoRequest("Unknown source: %s" % name)
    if chosen:
        joined = ",".join(chosen)
        argv.append("--sources=" + joined)
        shown.append('--sources="%s"' % joined)

    pairs = (
        ("gene", RE_GENE, "Gene symbol"),
        ("variant", RE_VARIANT, "Variation ID"),
        ("columns", RE_COLUMNS, "Column list"),
        ("joined-output", RE_FILENAME, "Joined CSV name"),
        ("template-output", RE_FILENAME, "Text file name"),
    )
    for key, pattern, label in pairs:
        value = _text(spec, key, pattern, label)
        if value:
            if key in ("gene", "variant"):
                value = re.sub(r"\s+", "", value)
            argv.append("--%s=%s" % (key, value))
            shown.append('--%s="%s"' % (key, value))

    if spec.get("template-output") and not spec.get("template"):
        raise NoNoRequest("A combined text file needs the template option turned on.")
    if spec.get("joined-output") and not chosen:
        raise NoNoRequest("A joined CSV needs at least one source selected.")

    return [(argv, None)], " ".join(shown)


def build_batch(spec):
    """Reimplements batch_txt_results.sh and batch_csv_results.sh.

    Those are bash scripts, so they don't run on Windows without WSL or Git
    Bash. The loop is simple enough to do here instead.
    """
    kind = spec.get("batch-kind")
    if kind not in ("txt", "csv"):
        raise NoNoRequest("Batch kind must be txt or csv.")

    raw = str(spec.get("variants", "") or "")
    if len(raw) > 200000:
        raise NoNoRequest("That variant list is too long.")
    ids = []
    for line in raw.replace(",", "\n").splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.isdigit():
            raise NoNoRequest("'%s' is not a Variation ID. One number per line." % line[:40])
        ids.append(line)
    if not ids:
        raise NoNoRequest("No variant IDs given.")
    if len(ids) > 5000:
        raise NoNoRequest("That's more than 5000 variants. Split it into batches.")

    folder = _text(spec, "batch-folder", RE_FOLDER, "Output folder") or "results"
    target = os.path.join(HERE, folder)
    os.makedirs(target, exist_ok=True)

    jobs = []
    for vid in ids:
        argv = [sys.executable, MAIN, "--loglevel=info"]
        if kind == "txt":
            argv += ["--expand", "--sources=" + BATCH_TXT_SOURCES, "--template",
                     "--template-output=" + os.path.join(folder, "variant_%s.txt" % vid),
                     "--variant=" + vid]
        else:
            argv += ["--template", "--sources=" + BATCH_CSV_SOURCES,
                     "--joined-output=" + os.path.join(folder, "%s.csv" % vid),
                     "--variant=" + vid]
        jobs.append((argv, "Variant %s" % vid))

    label = "batch %s: %d variants into %s\\" % (kind, len(ids), folder)
    return jobs, label


def recent_outputs(limit=12):
    out = []
    for name in os.listdir(HERE):
        if not name.lower().endswith((".csv", ".txt")):
            continue
        if name in ("requirements.txt", "requirements-catt.txt", "Notes.txt",
                    "test.txt", "example_input_file_for_llm_summary.txt"):
            continue
        path = os.path.join(HERE, name)
        if os.path.isfile(path):
            stat = os.stat(path)
            out.append({"name": name, "size": stat.st_size, "mtime": stat.st_mtime})
    out.sort(key=lambda item: item["mtime"], reverse=True)
    return out[:limit]

class Handler(BaseHTTPRequestHandler):
    server_version = "CATT-UI"

    def log_message(self, fmt, *args):
        pass # keep the console clean

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code, payload):
        self._send(code, json.dumps(payload))

    def do_GET(self): # noqa: N802
        path = self.path.split("?", 1)[0]
        query = self.path.split("?", 1)[1] if "?" in self.path else ""

        if path in ("/", "/index.html"):
            if not os.path.isfile(PAGE):
                return self._send(500, "catt-builder.html is missing from this folder.",
                                  "text/plain; charset=utf-8")
            with open(PAGE, "rb") as handle:
                return self._send(200, handle.read(), "text/html; charset=utf-8")

        if path == "/api/sources":
            return self._json(200, {"sources": source_status()})

        if path == "/api/log":
            since = 0
            for part in query.split("&"):
                if part.startswith("since="):
                    try:
                        since = max(0, int(part[6:]))
                    except ValueError:
                        since = 0
            payload = BLADERUNNER.snapshot(since)
            if not payload["running"]:
                payload["outputs"] = recent_outputs()
            return self._json(200, payload)

        return self._send(404, "Not found.", "text/plain; charset=utf-8")

    def do_POST(self): # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length > 2_000_000:
            return self._json(413, {"error": "Request too large."})
        raw = self.rfile.read(length) if length else b"{}"
        try:
            spec = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            return self._json(400, {"error": "Could not read that request."})
        if not isinstance(spec, dict):
            return self._json(400, {"error": "Could not read that request."})

        if path == "/api/run":
            try:
                if spec.get("mode") == "batch":
                    jobs, label = build_batch(spec)
                else:
                    jobs, label = build_single(spec)
                BLADERUNNER.start(jobs, label)
            except NoNoRequest as exc:
                return self._json(400, {"error": str(exc)})
            except Exception as exc: # noqa: BLE001
                return self._json(500, {"error": "Could not start: %s" % exc})
            return self._json(200, {"ok": True, "command": label})

        if path == "/api/stop":
            BLADERUNNER.stop()
            return self._json(200, {"ok": True})

        if path == "/api/reveal":
            try:
                if sys.platform == "win32":
                    os.startfile(HERE) # noqa: S606
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", HERE])
                else:
                    subprocess.Popen(["xdg-open", HERE])
            except Exception as exc: # noqa: BLE001
                return self._json(500, {"error": str(exc)})
            return self._json(200, {"ok": True})

        return self._json(404, {"error": "Not found."})


def free_port(preferred):
    for port in range(preferred, preferred + 40):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("Could not find a free port between %d and %d."
                     % (preferred, preferred + 40))


def main():
    parser = argparse.ArgumentParser(description="Run the CATT builder locally.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not os.path.isfile(MAIN):
        raise SystemExit(
            "main.py is not in this folder.\n"
            "Put catt_ui.py in the CATT project folder, next to main.py."
        )

    mimetypes.init()
    port = free_port(args.port)
    url = "http://127.0.0.1:%d/" % port
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    print("CATT builder running in " + url)
    print("This page is only reachable from this computer.")
    print("Close this window, or press Ctrl+C, to stop it.")
    print("Good luck on your project :)")
    print()

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        BLADERUNNER.stop()
        server.server_close()


if __name__ == "__main__":
    main()