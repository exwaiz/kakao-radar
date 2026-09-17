"""Local-only synthetic device test server; never attach real collector settings."""
import argparse
import base64
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from radar_server.app import create_app

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state",type=Path,default=Path(".state"))
    args=parser.parse_args()
    args.state.mkdir(parents=True,exist_ok=True)
    app=create_app(os.environ["RADAR_DATABASE_URL"])
    store=app.state.store; store.migrate()
    device,room,token=uuid4(),uuid4(),secrets.token_urlsafe(32)
    store.provision(device,room,token)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,"localhost")])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]),False)
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256()))
    cert_path=args.state/"server.pem"; key_path=args.state/"key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    (args.state/"test-args.json").write_text(json.dumps({"test_device":str(device),"test_room":str(room),
        "test_token_base64":base64.b64encode(token.encode()).decode(),
        "test_ca_base64":base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()}),encoding="utf-8")
    print("Synthetic fixture ready on localhost:8443; credentials in ignored state folder",flush=True)
    try:
        uvicorn.run(app,host="127.0.0.1",port=8443,ssl_keyfile=str(key_path),ssl_certfile=str(cert_path),access_log=False)
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM receipts WHERE device_id=%s",(device,))
            db.execute("DELETE FROM rooms WHERE device_id=%s",(device,))
            db.execute("DELETE FROM devices WHERE device_id=%s",(device,))

if __name__=="__main__": main()
