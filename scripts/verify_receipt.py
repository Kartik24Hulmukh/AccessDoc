from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.receipt import verify_receipt

def main()->int:
    parser=argparse.ArgumentParser(description='Verify that an AccessDoc receipt matches submitted UTF-8 text and a generated PDF.')
    parser.add_argument('receipt',type=Path);parser.add_argument('submitted_text',type=Path);parser.add_argument('pdf',type=Path)
    args=parser.parse_args()
    try: receipt=json.loads(args.receipt.read_text(encoding='utf-8'))
    except Exception as exc:
        print(json.dumps({'status':'FAIL','errors':[f'invalid receipt: {exc}']}));return 2
    errors=verify_receipt(receipt,args.submitted_text.read_bytes(),args.pdf.read_bytes())
    print(json.dumps({'status':'PASS' if not errors else 'FAIL','errors':errors},indent=2))
    return 0 if not errors else 1
if __name__=='__main__':raise SystemExit(main())
