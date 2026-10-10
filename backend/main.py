from fastapi import FastAPI

app = FastAPI(title="HCL Hackathon API")


@app.get("/api/health")
def health():
    return {"status": "ok"}
