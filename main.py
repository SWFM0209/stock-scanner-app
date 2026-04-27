from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"ok": True}

@app.get("/scan")
def scan():
    return {
        "data": [
            {"symbol":"2330","score":90,"close":600,"volume":1000000},
            {"symbol":"2317","score":80,"close":100,"volume":800000}
        ]
    }

@app.post("/ai/analyze")
def ai():
    return {"llm_analysis":"這是一個測試分析"}
