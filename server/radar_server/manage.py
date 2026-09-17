"""Local operator CLI. Tokens are entered secretly; never returned by the API."""
import argparse
import getpass
import os
from uuid import UUID
from .store import Store

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["migrate","provision","revoke","prune","delete-room"])
    parser.add_argument("--device",type=UUID)
    parser.add_argument("--room",type=UUID)
    args=parser.parse_args()
    store=Store(os.environ["RADAR_DATABASE_URL"])
    store.migrate()
    if args.command=="provision":
        if not args.device or not args.room: parser.error("--device and --room are required")
        store.provision(args.device,args.room,getpass.getpass("Device token (32+ characters): "))
        print("Device and room provisioned")
    elif args.command=="revoke":
        if not args.device: parser.error("--device is required")
        with store.connect() as db: db.execute("UPDATE devices SET active=false WHERE device_id=%s",(args.device,))
        print("Device revoked")
    elif args.command=="delete-room":
        if not args.device or not args.room: parser.error("--device and --room are required")
        print({"deleted_events":store.delete_room(args.device,args.room),"room_allowed":False})
    elif args.command=="prune": print(store.prune())
    else: print("Schema ready")

if __name__=="__main__": main()
