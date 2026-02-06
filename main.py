import argparse
import json
import threading
import time
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import yaml


@dataclass
class MatchEntry:
    params: dict[str, str] | None
    request_body: object | None
    status: int
    response: object


@dataclass
class RouteEntry:
    status: int
    default_response: object
    matches: list[MatchEntry] = field(default_factory=list)


def load_specs(spec_dir: Path) -> dict[tuple[str, str], RouteEntry]:
    routes: dict[tuple[str, str], RouteEntry] = {}

    for yaml_path in sorted(spec_dir.rglob("*.yaml")):
        parts = yaml_path.stem.split(".")
        if len(parts) < 2:
            continue
        name, method = parts[0], parts[1].upper()

        rel = yaml_path.relative_to(spec_dir).parent
        url_path = "/" + "/".join([*rel.parts, name]) if rel.parts else "/" + name

        with open(yaml_path) as f:
            config = yaml.safe_load(f) or {}

        default_status = config.get("status", 200)

        resp_file = yaml_path.with_name(f"{name}.{parts[1]}.resp.json")
        default_response = None
        if resp_file.exists():
            with open(resp_file) as f:
                default_response = json.load(f)

        matches: list[MatchEntry] = []
        for i, m in enumerate(config.get("matches", []), start=1):
            match_status = m.get("status", default_status)

            # Resolve response: inline > response_file > convention
            if "response" in m:
                match_response = m["response"]
            elif "response_file" in m:
                rf = yaml_path.parent / m["response_file"]
                with open(rf) as f:
                    match_response = json.load(f)
            else:
                conv_file = yaml_path.with_name(f"{name}.{parts[1]}.resp.{i}.json")
                match_response = None
                if conv_file.exists():
                    with open(conv_file) as f:
                        match_response = json.load(f)

            # Resolve request body: inline > request_file > convention
            req_body = None
            if "request" in m:
                req_body = m["request"]
            elif "request_file" in m:
                rf = yaml_path.parent / m["request_file"]
                with open(rf) as f:
                    req_body = json.load(f)
            else:
                req_file = yaml_path.with_name(f"{name}.{parts[1]}.req.{i}.json")
                if req_file.exists():
                    with open(req_file) as f:
                        req_body = json.load(f)

            matches.append(MatchEntry(
                params=m.get("params"),
                request_body=req_body,
                status=match_status,
                response=match_response,
            ))

        routes[(method, url_path)] = RouteEntry(
            status=default_status,
            default_response=default_response,
            matches=matches,
        )

    return routes


routes: dict[tuple[str, str], RouteEntry] = {}


class MockHandler(BaseHTTPRequestHandler):
    def handle_request(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        method = self.command.upper()
        query = parse_qs(parsed.query)
        # Flatten single-value params
        query_flat = {k: v[0] if len(v) == 1 else v for k, v in query.items()}

        # Check if any route exists for this path (any method)
        path_exists = any(p == path for (_, p) in routes)

        route = routes.get((method, path))
        if not route:
            status = 405 if path_exists else 404
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Method Not Allowed" if status == 405 else "Not Found"}).encode())
            return

        # Try matches (read body once, lazily)
        body = None
        body_read = False
        for m in route.matches:
            if m.params is not None:
                if all(query_flat.get(k) == v for k, v in m.params.items()):
                    self._send(m.status, m.response)
                    return
            elif m.request_body is not None:
                if not body_read:
                    body = self._read_body()
                    body_read = True
                if body == m.request_body:
                    self._send(m.status, m.response)
                    return

        self._send(route.status, route.default_response)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return None

    def _send(self, status: int, body: object):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if body is not None:
            self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        print(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else '?'}")

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request


def watch_reload(spec_dir: Path):
    mtimes: dict[str, float] = {}

    def snapshot():
        result = {}
        for p in spec_dir.rglob("*"):
            if p.is_file() and p.suffix in (".yaml", ".json"):
                result[str(p)] = p.stat().st_mtime
        return result

    mtimes = snapshot()
    while True:
        time.sleep(2)
        current = snapshot()
        if current != mtimes:
            mtimes = current
            global routes
            routes = load_specs(spec_dir)
            print("  [reload] Specs reloaded")


def main():
    parser = argparse.ArgumentParser(description="Lightweight HTTP mock server")
    parser.add_argument("-p", "--port", type=int, default=8000)
    parser.add_argument("-d", "--dir", type=str, default="./api")
    parser.add_argument("--reload", action="store_true", help="Watch for file changes")
    args = parser.parse_args()

    spec_dir = Path(args.dir).resolve()
    if not spec_dir.is_dir():
        print(f"Error: spec directory '{spec_dir}' not found")
        raise SystemExit(1)

    global routes
    routes = load_specs(spec_dir)

    print(f"serve-lhf listening on http://localhost:{args.port}")
    print(f"  spec dir: {spec_dir}")
    print(f"  routes loaded: {len(routes)}")
    for (method, path) in sorted(routes):
        r = routes[(method, path)]
        match_info = f" ({len(r.matches)} matches)" if r.matches else ""
        print(f"    {method:6s} {path}{match_info}")

    if args.reload:
        threading.Thread(target=watch_reload, args=(spec_dir,), daemon=True).start()
        print("  watching for changes...")

    server = HTTPServer(("", args.port), MockHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
