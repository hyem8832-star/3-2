import json
import os
import uuid
from datetime import datetime
from statistics import mean
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    firebase_admin = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


class DataItem(BaseModel):
    date: str
    value: float
    memo: str = ""


class Conversation(BaseModel):
    title: str = "새 대화"
    messages: list[dict[str, str]] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: Optional[str] = None


app = FastAPI(title="데이터 기반 AI 비서", version="1.0.0")
origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

memory_data: dict[str, dict[str, Any]] = {}
memory_conversations: dict[str, dict[str, Any]] = {}


def db():
    if not firebase_admin:
        return None
    try:
        if not firebase_admin._apps:
            raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            if raw:
                firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)))
            elif os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
                firebase_admin.initialize_app(credentials.ApplicationDefault())
            else:
                return None
        return firestore.client()
    except Exception:
        return None


def now():
    return datetime.utcnow().isoformat()


def clean(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def collection_items(name: str):
    client = db()
    if client:
        return [{"id": x.id, **{k: clean(v) for k, v in x.to_dict().items()}} for x in client.collection(name).stream()]
    source = memory_data if name == "data" else memory_conversations
    return [{"id": key, **value} for key, value in source.items()]


def save_item(name: str, item: dict[str, Any], item_id: Optional[str] = None):
    item_id = item_id or uuid.uuid4().hex[:12]
    item = {**item, "updated_at": now()}
    client = db()
    if client:
        client.collection(name).document(item_id).set(item)
    else:
        (memory_data if name == "data" else memory_conversations)[item_id] = item
    return {"id": item_id, **item}


def delete_item(name: str, item_id: str):
    client = db()
    if client:
        client.collection(name).document(item_id).delete()
    else:
        source = memory_data if name == "data" else memory_conversations
        if item_id not in source:
            raise HTTPException(404, "대상을 찾을 수 없습니다")
        del source[item_id]


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/data")
def create_data(item: DataItem):
    return save_item("data", item.model_dump())


@app.get("/api/data")
def list_data():
    return sorted(collection_items("data"), key=lambda x: x.get("date", ""), reverse=True)


@app.put("/api/data/{item_id}")
def update_data(item_id: str, item: DataItem):
    if not any(x["id"] == item_id for x in collection_items("data")):
        raise HTTPException(404, "데이터를 찾을 수 없습니다")
    return save_item("data", item.model_dump(), item_id)


@app.delete("/api/data/{item_id}")
def remove_data(item_id: str):
    delete_item("data", item_id)
    return {"deleted": True}


@app.get("/api/data/summary")
def summary():
    rows = list_data()
    values = [float(x["value"]) for x in rows]
    if not values:
        return {"period": "데이터 없음", "count": 0, "metrics": {"total": 0, "average": 0, "max": 0, "min": 0}, "trend": "데이터 없음"}
    trend = "유지"
    if len(values) > 1:
        if values[0] > values[-1]: trend = "최근 증가"
        elif values[0] < values[-1]: trend = "최근 감소"
    return {"period": f"{min(x['date'] for x in rows)} ~ {max(x['date'] for x in rows)}", "count": len(values), "metrics": {"total": round(sum(values), 2), "average": round(mean(values), 2), "max": max(values), "min": min(values)}, "trend": trend}


@app.post("/api/conversations")
def create_conversation(conversation: Conversation):
    return save_item("conversations", conversation.model_dump())


@app.get("/api/conversations")
def list_conversations():
    return sorted(collection_items("conversations"), key=lambda x: x.get("updated_at", ""), reverse=True)


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    matches = [x for x in collection_items("conversations") if x["id"] == conversation_id]
    if not matches: raise HTTPException(404, "대화를 찾을 수 없습니다")
    return matches[0]


@app.delete("/api/conversations/{conversation_id}")
def remove_conversation(conversation_id: str):
    delete_item("conversations", conversation_id)
    return {"deleted": True}


@app.post("/api/chat")
def chat(request: ChatRequest):
    context = summary()
    system = f"당신은 데이터 분석 비서입니다. 다음 요약을 근거로 한국어로 간결하게 답하세요: {json.dumps(context, ensure_ascii=False)}"
    answer = None
    key = os.getenv("OPENAI_API_KEY")
    if key and OpenAI:
        try:
            client = OpenAI(api_key=key, base_url=os.getenv("OPENAI_BASE_URL") or None)
            result = client.chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), messages=[{"role": "system", "content": system}, {"role": "user", "content": request.message}], max_tokens=300)
            answer = result.choices[0].message.content
        except Exception:
            answer = None
    if not answer:
        answer = f"현재 {context['count']}개 데이터의 평균은 {context['metrics']['average']}이고, 추세는 '{context['trend']}'입니다. (OPENAI_API_KEY를 설정하면 AI 답변이 활성화됩니다.)"
    messages = [{"role": "user", "content": request.message}, {"role": "assistant", "content": answer}]
    saved = save_item("conversations", {"title": request.message[:30], "messages": messages}, request.conversation_id)
    return {"answer": answer, "conversation_id": saved["id"], "summary": context}
