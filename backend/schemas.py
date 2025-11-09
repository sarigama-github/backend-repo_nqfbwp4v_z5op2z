"""
Database Schemas for VIYAN FASHION WORLD

Each Pydantic model corresponds to a MongoDB collection (lowercased name).
"""
from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional

# Admin settings (collection: "adminsettings")
class AdminSettings(BaseModel):
    username: str = Field(..., description="Admin username")
    password_hash: str = Field(..., description="SHA256 hash of admin password")
    upi_id: str = Field("viyan@upi", description="UPI ID for checkout")
    logo_url: Optional[str] = Field(None, description="Logo image URL")

# Product (collection: "product")
class Product(BaseModel):
    name: str
    description: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    price: int = Field(..., ge=0, description="Original price in INR")
    discount_percent: int = Field(0, ge=0, le=95)
    sizes: List[str] = Field(default_factory=lambda: ["XS","S","M","L","XL"]) 
    offer_minutes: Optional[int] = Field(None, ge=1, description="Time-limited offer in minutes")
    is_active: bool = True
