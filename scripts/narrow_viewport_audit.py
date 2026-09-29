#!/usr/bin/env python3
"""P1-2 narrow-screen audit: drives real headless Chromium over CDP.

For each viewport width (default 320/375/414/768) it loads the running app,
and measures: horizontal overflow (WCAG 1.4.10 Reflow), elements wider than
the viewport, interactive targets < 24x24 CSS px (WCAG 2.5.8), and the
summary-tile grid column count. Exit 0 only if every width passes.

Usage: narrow_viewport_audit.py URL [--widths 320,375] [--output PATH]
"""
import argparse, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
import websocket  # websocket-client

PROBE = r"""(() => {
  // Worst case: reveal every conditionally-hidden state (result tiles, errors, progress).
  for (const el of document.querySelectorAll('main [hidden]')) el.hidden = false;
  const vw = document.documentElement.clientWidth;
  const sw = document.documentElement.scrollWidth;
  const wide = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const cs = getComputedStyle(el);
    if (cs.position === 'absolute' && r.bottom < 0) continue;  // off-screen skip link
    if (r.right > vw + 1 || r.left < -1) wide.push((el.tagName + '#' + (el.id||'') + '.' + (el.className||'')).slice(0,80));
  }
  const small = [];
  for (const el of document.querySelectorAll('a[href],button,input,select,textarea,summary')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (getComputedStyle(el).visibility === 'hidden') continue;
    const inline = el.tagName === 'A' && getComputedStyle(el).display === 'inline';
    if (!inline && (r.width < 24 || r.height < 24)) small.push(el.tagName + '#' + (el.id||'') + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
  }
  const sum = document.querySelector('.summary');
  const cols = sum ? getComputedStyle(sum).gridTemplateColumns.split(' ').filter(Boolean).length : null;
  return JSON.stringify({vw, sw, overflow: sw > vw, wide: wide.slice(0,20), wide_count: wide.length, small_targets: small, summary_cols: cols, has_main: !!document.querySelector('main')});
})()"""


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('--widths', default='320,375,414,768')
    ap.add_argument('--output', default=None)
    a = ap.parse_args(argv)
    exe = shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')
    if not exe:
        print('chromium not found', file=sys.stderr); return 2
    port = free_port(); prof = tempfile.mkdtemp(prefix='ad-p12-')
    proc = subprocess.Popen([exe, '--headless=new', '--no-sandbox', '--disable-gpu', '--remote-allow-origins=*', f'--remote-debugging-port={port}',
                             f'--user-data-dir={prof}', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15; targets = None
        while time.monotonic() < deadline:
            try:
                targets = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json', timeout=1)); break
            except OSError:
                time.sleep(0.1)
        page = next(t for t in targets if t.get('type') == 'page')
        ws = websocket.create_connection(page['webSocketDebuggerUrl'], timeout=15, suppress_origin=True)
        mid = [0]
        def call(method, **params):
            mid[0] += 1; ws.send(json.dumps({'id': mid[0], 'method': method, 'params': params}))
            while True:
                m = json.loads(ws.recv())
                if m.get('id') == mid[0]:
                    if 'error' in m: raise RuntimeError(m['error'])
                    return m.get('result', {})
        call('Page.enable')
        results = {}
        for w in [int(x) for x in a.widths.split(',')]:
            call('Emulation.setDeviceMetricsOverride', width=w, height=800, deviceScaleFactor=1, mobile=True)
            call('Page.navigate', url=a.url)
            for _ in range(100):
                st = call('Runtime.evaluate', expression='document.readyState', returnByValue=True)['result'].get('value')
                if st == 'complete': break
                time.sleep(0.05)
            r = json.loads(call('Runtime.evaluate', expression=PROBE, returnByValue=True)['result']['value'])
            r['pass'] = r['has_main'] and (not r['overflow']) and r['wide_count'] == 0 and not r['small_targets'] and (w > 420 or r['summary_cols'] in (None, 1))
            results[str(w)] = r
            print(w, 'PASS' if r['pass'] else 'FAIL', json.dumps(r))
        ws.close()
    finally:
        proc.terminate()
        try: proc.wait(5)
        except subprocess.TimeoutExpired: proc.kill()
        shutil.rmtree(prof, ignore_errors=True)
    ok = all(r['pass'] for r in results.values())
    if a.output:
        with open(a.output, 'w') as f: json.dump({'url': a.url, 'pass': ok, 'widths': results}, f, indent=2)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
