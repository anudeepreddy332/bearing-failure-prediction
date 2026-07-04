# src/api/predict_api.py
"""
FastAPI endpoint for real-time bearing RUL prediction
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pickle
import pandas as pd

app = FastAPI(title="Bearing RUL Prediction API")

# Load model at startup
with open('models/lightgbm_v2_tuned.pkl', 'rb') as f:
    model = pickle.load(f)

# Load feature names
features = pd.read_csv('data/processed/selected_features.csv')['feature'].tolist()


class PredictionRequest(BaseModel):
    features: dict  # Feature name -> value mapping


class PredictionResponse(BaseModel):
    predicted_rul_hours: float
    risk_level: str  # "critical", "warning", "normal"
    recommended_action: str


@app.post("/predict", response_model=PredictionResponse)
def predict_rul(request: PredictionRequest):
    """Predict remaining useful life for a bearing"""

    try:
        # Convert to DataFrame
        feature_vector = pd.DataFrame([request.features])

        # Ensure correct feature order
        feature_vector = feature_vector[features]

        # Predict
        rul_hours = float(model.predict(feature_vector)[0])

        # Determine risk level
        if rul_hours < 50:
            risk_level = "critical"
            action = "Schedule emergency maintenance within 24 hours"
        elif rul_hours < 150:
            risk_level = "warning"
            action = "Schedule maintenance within 3-5 days"
        else:
            risk_level = "normal"
            action = "Continue normal monitoring"

        return PredictionResponse(
            predicted_rul_hours=round(rul_hours, 2),
            risk_level=risk_level,
            recommended_action=action
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/health")
def health_check():
    return {"status": "healthy", "model": "lightgbm_v2_tuned"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
