"""Side experiment: turn the score into 3 levels and try CLASSIFIERS (Naive Bayes, SVC, ...).

Why: Naive Bayes and SVC are classification algorithms, so they need a category target, not a number.
We split Mental_Health_Score into  At risk (<5) / Moderate (5-7) / Healthy (>=7).
Run:  python -m src.classification"""
import warnings, json
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.model_selection import train_test_split, GroupShuffleSplit, GroupKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OrdinalEncoder, OneHotEncoder
from sklearn.naive_bayes import GaussianNB
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier, VotingClassifier
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, ConfusionMatrixDisplay
from sklearn.base import clone
from .config import *
from .data import load_clean, get_xy, get_groups



def main():
    warnings.filterwarnings("ignore")
    df = load_clean(); X, y_num = get_xy(df); groups = get_groups(df)
    y = pd.cut(y_num, BAND_EDGES, labels=BAND_LABELS, right=False)
    print(y.value_counts().to_dict())

    def prep(with_cats=True):
        t = [("n", StandardScaler(), NUMERIC), ("o", OrdinalEncoder(categories=[STRESS_ORDER]), ORDINAL)]
        if with_cats:
            t.append(("c", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=5, sparse_output=False), NOMINAL))
        return ColumnTransformer(t)

    P = lambda m, c=True: Pipeline([("prep", prep(c)), ("m", m)])
    models = {
        "Naive Bayes (Gaussian)": P(GaussianNB(var_smoothing=1e-2), False),
        "Logistic Regression": P(LogisticRegression(C=1, max_iter=2000)),
        "SVC (SVM, rbf)": P(SVC(C=2, gamma="scale", probability=True, random_state=RANDOM_STATE)),
        "Random Forest": P(RandomForestClassifier(300, min_samples_leaf=5, max_features=0.5, random_state=RANDOM_STATE)),
        "Gradient Boosting": P(HistGradientBoostingClassifier(learning_rate=.05, max_depth=3, max_iter=300, min_samples_leaf=30, random_state=RANDOM_STATE)),
    }
    models["Voting Ensemble (soft)"] = VotingClassifier(
        [("nb", models["Naive Bayes (Gaussian)"]), ("svc", models["SVC (SVM, rbf)"]),
         ("rf", models["Random Forest"]), ("gb", models["Gradient Boosting"])], voting="soft")

    Xtr, Xte, ytr, yte, gtr, _ = train_test_split(X, y, groups, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y)
    tri, tei = next(GroupShuffleSplit(1, test_size=TEST_SIZE, random_state=RANDOM_STATE).split(X, y, groups))
    rows = []
    for n, m in models.items():
        cv = cross_val_score(m, Xtr, ytr, cv=GroupKFold(5), groups=gtr, scoring="accuracy").mean()
        m.fit(Xtr, ytr)
        u = clone(m).fit(X.iloc[tri], y.iloc[tri])
        rows.append({"Model": n, "cv_accuracy": cv, "train_accuracy": accuracy_score(ytr, m.predict(Xtr)),
                     "test_accuracy": accuracy_score(yte, m.predict(Xte)), "test_f1_macro": f1_score(yte, m.predict(Xte), average="macro"),
                     "unseen_profiles_accuracy": accuracy_score(y.iloc[tei], u.predict(X.iloc[tei]))})
        print(rows[-1])
    res = pd.DataFrame(rows).round(4); res.to_csv(REPORT_DIR / "classifier_experiment_comparison.csv", index=False)
    print(res.to_string(index=False))

    best = res.sort_values("cv_accuracy", ascending=False).iloc[0].Model
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    ConfusionMatrixDisplay(confusion_matrix(yte, models[best].predict(Xte), labels=BAND_LABELS), display_labels=["At risk", "Moderate", "Healthy"]).plot(ax=ax, colorbar=False)
    ax.set_title(f"{best}\nconfusion matrix (test set)"); plt.tight_layout(); plt.savefig(REPORT_DIR / "classification_confusion_matrix.png", dpi=130)


if __name__ == "__main__":
    main()
