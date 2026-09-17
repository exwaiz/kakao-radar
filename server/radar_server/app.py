import os
import time
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from .store import Store
from .analysis_models import ProfileUpdate
from .analysis_store import AnalysisStore, VersionConflict

MAX_BODY = 1024*1024
PROFILE_SCHEMA = ProfileUpdate.model_json_schema()
# Inline the sole nested model so OpenAPI's document root has no dangling $defs ref.
PROFILE_SCHEMA["properties"]["profile"] = PROFILE_SCHEMA.pop("$defs")["InterestProfile"]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    event_id: UUID
    room_id: UUID
    sender_alias: str = Field(min_length=1,max_length=128,pattern=r"^(unknown|[a-f0-9]{64})$")
    text: str = Field(min_length=1,max_length=16000)
    source_time: int | None = Field(default=None,ge=1)
    observed_at: int = Field(ge=1)
    urls: list[str] = Field(max_length=50)
    quality: str = Field(pattern=r"^(structured|uncertain_window|fallback_no_message_time)$")
    parser_version: int = Field(ge=1,le=100)

    @field_validator("event_id","room_id",mode="before")
    @classmethod
    def uuid_from_wire(cls,value):
        return UUID(value) if isinstance(value,str) else value

    @field_validator("urls")
    @classmethod
    def valid_urls(cls,values):
        if any(len(v)>4096 or not v.startswith(("https://","http://")) for v in values):
            raise ValueError("Invalid URLs")
        return values

    @field_validator("observed_at")
    @classmethod
    def not_future(cls,value):
        if value > int(time.time()*1000)+300000:
            raise ValueError("Future timestamp")
        return value


def create_app(dsn=None):
    store = Store(dsn or os.environ["RADAR_DATABASE_URL"])
    @asynccontextmanager
    async def lifespan(app):
        store.migrate()
        yield
    app = FastAPI(title="Kakao Radar",version="0.4.0",lifespan=lifespan)
    app.state.store = store
    analysis = AnalysisStore(store)
    app.state.analysis = analysis
    bearer = HTTPBearer(auto_error=False)

    def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or len(credentials.credentials)>512:
            raise HTTPException(401,"Authentication required")
        device = store.authenticate(credentials.credentials)
        if device is None:
            raise HTTPException(401,"Invalid credentials")
        return device

    @app.exception_handler(RequestValidationError)
    async def safe_validation(request,exc):
        return JSONResponse({"detail":"Invalid request"},status_code=422)

    @app.exception_handler(psycopg.Error)
    async def safe_database_error(request,exc):
        # Database error strings may contain row data; do not expose them.
        return JSONResponse({"detail":"Storage temporarily unavailable"},status_code=503)

    @app.exception_handler(PermissionError)
    async def revoked(request,exc):
        return JSONResponse({"detail":"Invalid credentials"},status_code=401)

    @app.get("/health")
    def health():
        return {"status":"ok","version":"0.4.0"}

    @app.post("/v1/messages/batch")
    async def batch(request: Request, device=Depends(principal)):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>MAX_BODY:
                raise HTTPException(413,"Batch too large")
        import json
        try:
            envelope=json.loads(raw)
            if not isinstance(envelope,dict) or set(envelope)!={"items"} or not isinstance(envelope["items"],list) or not 1<=len(envelope["items"])<=100:
                raise ValueError()
        except (ValueError,UnicodeError):
            raise HTTPException(422,"Invalid batch")
        valid, invalid, order = [], {}, []
        for item in envelope["items"]:
            try:
                event=str(UUID(item["event_id"]))
                if event in order:
                    raise ValueError()
            except (ValueError,TypeError,KeyError,AttributeError):
                raise HTTPException(422,"Invalid or duplicate event ID")
            order.append(event)
            try:
                valid.append(Message.model_validate(item))
            except (ValidationError,ValueError):
                invalid[event]={"event_id":event,"status":"rejected","reason":"invalid_message"}
        committed = await run_in_threadpool(store.ingest,device,valid)
        responses={r["event_id"]:r for r in committed}
        responses.update(invalid)
        return {"results":[responses[e] for e in order]}

    @app.get("/v1/status")
    def status(device=Depends(principal)):
        return store.status(device)

    @app.delete("/v1/rooms/{room_id}/data")
    def delete(room_id: UUID,device=Depends(principal)):
        return {"deleted_events":store.delete_room(device,room_id),"room_allowed":False}

    @app.get("/v1/profile")
    def profile(device=Depends(principal)):
        return analysis.profile(device)

    @app.put("/v1/profile",openapi_extra={"requestBody":{"required":True,"content":{"application/json":{"schema":PROFILE_SCHEMA}}}})
    async def update_profile(request: Request,device=Depends(principal)):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>32768:
                raise HTTPException(413,"Profile too large")
        try:
            update=ProfileUpdate.model_validate_json(raw)
        except ValidationError:
            raise HTTPException(422,"Invalid profile") from None
        try:
            return await run_in_threadpool(analysis.update_profile,device,update)
        except VersionConflict:
            raise HTTPException(409,"Profile version changed") from None

    @app.get("/v1/analysis/status")
    def analysis_status(device=Depends(principal)):
        return analysis.status(device)

    @app.get("/v1/analysis/jobs")
    def analysis_jobs(limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0,le=100000),device=Depends(principal)):
        return {"items":analysis.jobs(device,limit,offset)}

    @app.get("/v1/rooms/{room_id}/summaries")
    def summaries(room_id: UUID,limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0,le=100000),candidates_only: bool=False,device=Depends(principal)):
        return {"items":analysis.summaries(device,room_id,limit,offset,candidates_only)}

    @app.get("/v1/summaries/{summary_id}/evidence")
    def evidence(summary_id: UUID,device=Depends(principal)):
        result=analysis.evidence(device,summary_id)
        if result is None:
            raise HTTPException(404,"Summary not found")
        return result

    return app
