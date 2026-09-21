"""Local operator CLI. Tokens are entered secretly; never returned by the API."""
import argparse
import getpass
import json
import os
from uuid import UUID
from .store import RouteDestinationConflict, RouteVersionConflict, Store

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["migrate","provision","revoke","prune","delete-room","list-rooms","set-route"])
    parser.add_argument("--device",type=UUID)
    parser.add_argument("--room",type=UUID)
    parser.add_argument("--name",default="")
    parser.add_argument("--chat-id")
    parser.add_argument("--thread-id",type=int)
    parser.add_argument("--expected-version",type=int,default=0)
    parser.add_argument("--disable",action="store_true")
    args=parser.parse_args()
    store=Store(os.environ["RADAR_DATABASE_URL"])
    store.migrate()
    if args.command=="provision":
        if not args.device or not args.room: parser.error("--device and --room are required")
        store.provision(args.device,args.room,getpass.getpass("Device token (32+ characters): "),args.name)
        print("Device and room provisioned")
    elif args.command=="revoke":
        if not args.device: parser.error("--device is required")
        with store.connect() as db: db.execute("UPDATE devices SET active=false WHERE device_id=%s",(args.device,))
        print("Device revoked")
    elif args.command=="delete-room":
        if not args.device or not args.room: parser.error("--device and --room are required")
        print({"deleted_events":store.delete_room(args.device,args.room),"room_allowed":False})
    elif args.command=="list-rooms":
        if not args.device: parser.error("--device is required")
        print(json.dumps(store.status(args.device),default=str,ensure_ascii=False,indent=2))
    elif args.command=="set-route":
        if not args.device or not args.room or not args.chat_id: parser.error("--device, --room and --chat-id are required")
        try:
            result=store.update_route(args.device,args.room,chat_id=args.chat_id,message_thread_id=args.thread_id,
                display_name=args.name,enabled=not args.disable,expected_version=args.expected_version)
        except RouteVersionConflict:
            parser.exit(1,"Route version changed; list rooms and retry with the current version\n")
        except RouteDestinationConflict:
            parser.exit(1,"Telegram destination is already assigned to another room\n")
        except ValueError:
            parser.exit(1,"Invalid Telegram route\n")
        if result is None: parser.error("room is not provisioned or allowed")
        print(json.dumps(result,default=str,ensure_ascii=False))
    elif args.command=="prune": print(store.prune())
    else: print("Schema ready")

if __name__=="__main__": main()
