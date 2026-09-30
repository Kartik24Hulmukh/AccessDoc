from pathlib import Path
import json, sys
from playwright.sync_api import sync_playwright
ROOT=Path('/data/AccessDoc')
html=(ROOT/'public/index.html').read_text(); js=(ROOT/'public/static/app.js').read_text()
A={'violations':[{'id':'image-alt','impact':'serious','help':'Synthetic A','nodes':[{'target':['#synthetic-a']}]}]}
B={'violations':[{'id':'label','impact':'moderate','help':'Synthetic B','nodes':[{'target':['#synthetic-b']}]}]}
posts=[]; held=[]; mode={'hold':False}
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,executable_path='/usr/local/bin/chromium')
 context=browser.new_context(accept_downloads=True)
 def route(r):
  path=r.request.url.split('127.0.0.1:18799')[-1]
  if path=='/': r.fulfill(status=200,content_type='text/html',body=html)
  elif path=='/static/app.js': r.fulfill(status=200,content_type='application/javascript',body=js)
  elif path=='/sample/axe-sample.json': r.fulfill(status=200,content_type='application/json',body=json.dumps(B))
  elif path=='/api/bundle':
   posts.append({'path':path,'payload':r.request.post_data_json})
   if mode['hold']: held.append(r)
   else: r.fulfill(status=200,content_type='application/zip',body=b'SYNTHETIC-NOT-A-VALID-ZIP')
  elif path=='/api/remediate':
   posts.append({'path':path,'payload':r.request.post_data_json})
   r.fulfill(status=200,content_type='application/json',body=json.dumps({'guidance':'Synthetic B plan','fallback':True,'violations_considered':1}))
  else: r.fulfill(status=200,body='')
 context.route('**/*',route)
 page=context.new_page(); page.goto('http://127.0.0.1:18799/')
 page.locator('#client').fill('Synthetic Client A'); page.locator('#agency').fill('Synthetic Agency')
 page.locator('#evidence-file').set_input_files({'name':'synthetic-a.json','mimeType':'application/json','buffer':json.dumps(A).encode()})
 page.locator('#generate').click(); page.locator('#result').wait_for(state='visible')
 page.locator('#remediate').click(); page.locator('#errors').wait_for(state='visible')
 observations={'file_only_remediation_error':page.locator('#errors').inner_text(), 'file_only_remediation_posts':sum(x['path']=='/api/remediate' for x in posts)}
 page.locator('#sample').click(); page.wait_for_function("document.querySelector('#scanner').value.includes('Synthetic B')")
 page.locator('#generate').click(); page.locator('#result').wait_for(state='visible')
 observations['sample_bundle_evidence_id']=json.loads(posts[-1]['payload']['scanner_input'])['violations'][0]['id']
 observations['sample_selected_filename']=page.locator('#file-name').inner_text()
 page.locator('#remediate').click(); page.locator('#remediation-out').wait_for(state='visible')
 observations['remediation_evidence_id']=posts[-1]['payload']['scanner_input']['violations'][0]['id']
 page.locator('#generate').click(); page.locator('#result').wait_for(state='visible')
 observations['old_remediation_visible_after_regeneration']=page.locator('#remediation-out').is_visible()
 observations['download_href_before_bad_retry']=bool(page.locator('#download').get_attribute('href'))
 page.locator('#evidence-file').set_input_files({'name':'too-large.json','mimeType':'application/json','buffer':b'x'*2000001})
 page.locator('#generate').click(); page.locator('#errors').wait_for(state='visible')
 observations['download_href_after_bad_retry']=page.locator('#download').get_attribute('href')
 observations['result_visible_after_bad_retry']=page.locator('#result').is_visible()
 page.locator('#evidence-file').set_input_files([])
 page.locator('#client').fill('Synthetic Pending Client'); mode['hold']=True
 page.locator('#generate').click(); page.wait_for_timeout(100)
 observations['pending_bundle_requests']=len(held)
 observations['generate_disabled_while_pending']=page.locator('#generate').is_disabled()
 observations['cancel_or_reset_controls']=page.locator('button,input').evaluate_all("es=>es.filter(e=>/cancel|reset/i.test(e.textContent)||e.type==='reset').length")
 observations['sample_enabled_while_pending']=page.locator('#sample').is_enabled()
 page.locator('#sample').click(); page.wait_for_function("document.querySelector('#client').value==='Northstar Community Bank'")
 observations['submitted_client']=posts[-1]['payload']['client_name']
 observations['visible_client_during_pending']=page.locator('#client').input_value()
 held[0].fulfill(status=200,content_type='application/zip',body=b'SYNTHETIC-OLD-RESPONSE')
 page.locator('#result').wait_for(state='visible')
 observations['old_response_shown_after_input_change']=page.locator('#result').is_visible()
 browser.close()
print(json.dumps({'scope':'Synthetic intercepted loopback UI baseline; ZIP bytes not real bundles', 'observations':observations},indent=2))
