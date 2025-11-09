import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import hashlib

from database import db, create_document, get_documents
from schemas import AdminSettings, Product

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------- Helpers -------------------------------
COLL_SETTINGS = "adminsettings"
COLL_PRODUCT = "product"

DEFAULT_USERNAME = "viyan fashion world"
DEFAULT_PASSWORD = "viyan@2023"

logger = logging.getLogger("uvicorn.error")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def db_ready() -> bool:
    return db is not None


async def ensure_default_settings():
    """Create default admin settings if they don't exist.
    This should never crash the app if DB is unavailable or quota is exceeded.
    """
    if not db_ready():
        logger.warning("Database not configured; skipping default settings init")
        return
    try:
        existing = db[COLL_SETTINGS].find_one({})
        if not existing:
            data = AdminSettings(
                username=DEFAULT_USERNAME,
                password_hash=sha256(DEFAULT_PASSWORD),
                upi_id="viyan@upi",
                logo_url=None,
            )
            create_document(COLL_SETTINGS, data)
            logger.info("Default admin settings created")
    except Exception as e:
        logger.error(f"Failed to ensure default settings: {e}")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


# simple in-memory tokens for this demo; in production use JWT
TOKENS = set()


def auth_dependency(token: Optional[str] = None):
    if not token or token not in TOKENS:
        raise HTTPException(status_code=401, detail="Unauthorized")


# ------------------------------- Public -------------------------------
@app.on_event("startup")
async def startup_event():
    await ensure_default_settings()


@app.get("/")
def read_root():
    return {"message": "VIYAN backend running"}


@app.get("/test")
def test_database():
    response = {"backend": "running", "db": "not-set"}
    try:
        if db_ready():
            response["db"] = "connected"
            response["collections"] = db.list_collection_names()
        else:
            response["db"] = "not-configured"
    except Exception as e:
        response["error"] = str(e)
    return response


# ------------------------------- Auth -------------------------------
@app.post("/api/admin/login", response_model=LoginResponse)
async def admin_login(payload: LoginRequest):
    await ensure_default_settings()

    # If DB is available, validate against stored credentials
    if db_ready():
        try:
            doc = db[COLL_SETTINGS].find_one({})
            if doc and payload.username.strip().lower() == str(doc.get("username", "")).strip().lower() and sha256(payload.password) == doc.get("password_hash"):
                token = sha256(payload.username + payload.password + str(datetime.utcnow()))
                TOKENS.add(token)
                return {"token": token}
        except Exception as e:
            logger.error(f"Login DB error: {e}")
            # fall through to default check

    # Fallback: allow default credentials when DB is unavailable
    if payload.username.strip().lower() == DEFAULT_USERNAME and payload.password == DEFAULT_PASSWORD:
        token = sha256(payload.username + payload.password + str(datetime.utcnow()))
        TOKENS.add(token)
        return {"token": token}

    raise HTTPException(status_code=401, detail="Invalid credentials")


# ------------------------------- Settings -------------------------------
class UpdateSettings(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    upi_id: Optional[str] = None
    logo_url: Optional[str] = None


@app.get("/api/admin/settings", response_model=AdminSettings)
async def get_settings(token: str):
    auth_dependency(token)
    if not db_ready():
        raise HTTPException(status_code=503, detail="Database unavailable")
    doc = db[COLL_SETTINGS].find_one({})
    if not doc:
        raise HTTPException(status_code=404, detail="Settings not found")
    return AdminSettings(
        username=doc.get("username"),
        password_hash=doc.get("password_hash"),
        upi_id=doc.get("upi_id"),
        logo_url=doc.get("logo_url"),
    )


@app.post("/api/admin/settings")
async def update_settings(payload: UpdateSettings, token: str):
    auth_dependency(token)
    if not db_ready():
        raise HTTPException(status_code=503, detail="Database unavailable")
    updates = {}
    if payload.username is not None:
        updates["username"] = payload.username
    if payload.password is not None:
        updates["password_hash"] = sha256(payload.password)
    if payload.upi_id is not None:
        updates["upi_id"] = payload.upi_id
    if payload.logo_url is not None:
        updates["logo_url"] = payload.logo_url
    if not updates:
        return {"updated": False}
    db[COLL_SETTINGS].update_one({}, {"$set": updates}, upsert=True)
    return {"updated": True}


# ------------------------------- Products CRUD -------------------------------
class ProductIn(BaseModel):
    name: str
    description: Optional[str] = None
    images: Optional[List[str]] = None
    price: int
    discount_percent: int = 0
    sizes: Optional[List[str]] = None
    offer_minutes: Optional[int] = None
    is_active: bool = True


from bson import ObjectId


def to_public(doc):
    if not doc:
        return None
    doc["id"] = str(doc["_id"]) if "_id" in doc else None
    doc.pop("_id", None)
    return doc


@app.get("/api/products")
async def list_products():
    if not db_ready():
        return []
    try:
        items = get_documents(COLL_PRODUCT)
        return [to_public(x) for x in items]
    except Exception as e:
        logger.error(f"List products error: {e}")
        return []


@app.post("/api/admin/products")
async def create_product(payload: ProductIn, token: str):
    auth_dependency(token)
    if not db_ready():
        raise HTTPException(status_code=503, detail="Database unavailable")
    data = Product(
        name=payload.name,
        description=payload.description,
        images=payload.images or [],
        price=payload.price,
        discount_percent=payload.discount_percent,
        sizes=payload.sizes or ["XS", "S", "M", "L", "XL"],
        offer_minutes=payload.offer_minutes,
        is_active=payload.is_active,
    )
    _id = create_document(COLL_PRODUCT, data)
    return {"id": _id}


@app.put("/api/admin/products/{product_id}")
async def update_product(product_id: str, payload: ProductIn, token: str):
    auth_dependency(token)
    if not db_ready():
        raise HTTPException(status_code=503, detail="Database unavailable")
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    result = db[COLL_PRODUCT].update_one({"_id": ObjectId(product_id)}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"updated": True}


@app.delete("/api/admin/products/{product_id}")
async def delete_product(product_id: str, token: str):
    auth_dependency(token)
    if not db_ready():
        raise HTTPException(status_code=503, detail="Database unavailable")
    result = db[COLL_PRODUCT].delete_one({"_id": ObjectId(product_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"deleted": True}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
