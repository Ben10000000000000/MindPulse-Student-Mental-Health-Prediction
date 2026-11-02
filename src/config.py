"""Central project settings."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
XLSX_PATH=ROOT/"data"/"MindPulse_Student_Mental_Health_Dataset_v1.xlsx"
DATA_PATH=ROOT/"data"/"student_social_media_mental_health.csv"
MODEL_PATH=ROOT/"models"/"mental_health_model.joblib"
REPORT_DIR=ROOT/"reports"
TARGET="Mental_Health_Score"
RANDOM_STATE=42
TEST_SIZE=0.20
NUMERIC=["Age","Avg_Daily_Usage_Hours","Daily_Unlocks","Study_Hours","Physical_Activity_Hours","Sleep_Hours_Per_Night"]
ORDINAL=["Stress_Level"]
STRESS_ORDER=["Low","Medium","High","Very High"]
NOMINAL=["Gender","Academic_Level","Employment_Status","Most_Used_Platform","Purpose_Of_Use","Country"]
FEATURES=NUMERIC+ORDINAL+NOMINAL
GROUP_KEYS=["Country","Gender","Academic_Level","Employment_Status","Most_Used_Platform","Purpose_Of_Use","Stress_Level"]
# Single score-band definition shared by training, evaluation, and the API: low < 5, moderate 5-6.9, healthy >= 7.
BAND_EDGES=[0,5.0,7.0,10.000001]
BAND_LABELS=["At risk (low score)","Moderate","Healthy (high score)"]
