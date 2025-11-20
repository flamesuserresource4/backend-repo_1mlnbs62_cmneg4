import os
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
import requests
from bs4 import BeautifulSoup

from database import create_document

app = FastAPI(title="Qarakal Site Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ContactMessageModel(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    company: Optional[str] = Field(None, max_length=120)
    message: str = Field(..., min_length=5, max_length=5000)


@app.get("/")
def read_root():
    return {"message": "Qarakal backend running"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.post("/api/contact")
def submit_contact(msg: ContactMessageModel):
    try:
        doc_id = create_document("contactmessage", msg)
        return {"ok": True, "id": doc_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scrape")
def scrape_site(url: Optional[str] = None) -> Dict[str, Any]:
    """
    Scrape basic structured content from the provided URL (default qarakal.ai)
    and return a normalized content model for the frontend to render.
    """
    target = url or "https://qarakal.ai/"
    try:
        resp = requests.get(target, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch site: {e}")

    soup = BeautifulSoup(resp.text, "html.parser")

    # Title and meta
    title = (soup.title.string.strip() if soup.title and soup.title.string else None)
    description = None
    og_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()

    # Collect headings and sections
    h1s = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h2s = [h.get_text(strip=True) for h in soup.find_all("h2")]
    h3s = [h.get_text(strip=True) for h in soup.find_all("h3")]

    # Simple heuristic for hero: first h1 + optional subtitle paragraph near it
    hero_heading = h1s[0] if h1s else title
    hero_sub = None
    if hero_heading:
        first_h1 = soup.find("h1")
        if first_h1:
            # Look for a sibling paragraph
            sib_p = first_h1.find_next(["p", "h2", "div"])
            if sib_p:
                hero_sub = sib_p.get_text(strip=True)[:300]

    # Navigation links (top-level anchors)
    nav_links: List[Dict[str, str]] = []
    nav = soup.find("nav")
    if nav:
        for a in nav.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"].strip()
            if text and href and not text.lower().startswith("#"):
                nav_links.append({"label": text, "href": href})
    else:
        # fallback: first 5 anchors near top
        anchors = soup.find_all("a", href=True)[:8]
        for a in anchors:
            text = a.get_text(strip=True)
            href = a["href"].strip()
            if text:
                nav_links.append({"label": text, "href": href})

    # Sections: group by h2
    sections: List[Dict[str, Any]] = []
    for h2 in soup.find_all("h2"):
        content_parts: List[str] = []
        node = h2
        # collect following siblings until next h2
        for sib in h2.next_siblings:
            if getattr(sib, "name", None) == "h2":
                break
            if getattr(sib, "name", None) in ("p", "h3", "ul", "ol", "div"):
                text = BeautifulSoup(str(sib), "html.parser").get_text(" ", strip=True)
                if text:
                    content_parts.append(text)
        sec_text = "\n".join(content_parts)[:1200]
        sections.append({
            "title": h2.get_text(strip=True),
            "body": sec_text
        })

    # Images
    images = []
    for img in soup.find_all("img"):
        src = img.get("src")
        alt = img.get("alt", "")
        if src:
            images.append({"src": src, "alt": alt})
    images = images[:10]

    data = {
        "source": target,
        "title": title,
        "description": description,
        "hero": {
            "heading": hero_heading,
            "subheading": hero_sub
        },
        "nav": nav_links[:8],
        "sections": sections[:6] if sections else [
            {
                "title": "About",
                "body": description or "We build advanced quantitative computing and AI solutions."
            }
        ],
        "images": images
    }
    return data


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        from database import db

        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
