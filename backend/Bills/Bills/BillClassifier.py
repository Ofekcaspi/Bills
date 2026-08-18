import pickle
import re
from pathlib import Path

import pdfplumber
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

from .hebrew_text import reverse_words_char_by_char


class DocumentTextExtractor:
    """Reads the words (unproccessed) out of a .pdf or .txt file."""

    def extract_words(self, file_path: Path) -> list[str]:
        file_path = Path(file_path)
        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            return self._from_pdf(file_path)

        if suffix == ".txt":
            return self._from_txt(file_path)

        raise ValueError(f"Unsupported file type: {file_path}")

    def _from_pdf(self, pdf_path: Path) -> list[str]:
        words = []

        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_words = page.extract_words()
                if not page_words:
                    continue

                for word_data in page_words:
                    if "text" in word_data:
                        words.append(word_data["text"])

        return words

    def _from_txt(self, txt_path: Path) -> list[str]:
        text = txt_path.read_text(encoding="utf-8", errors="replace")
        return reverse_words_char_by_char(text)


def clean_words(words):
    cleaned = []

    for word in words:
        original = word.strip()

        if not original:
            continue

        if re.fullmatch(r"[\w\.-]+@[\w\.-]+\.\w+", original):
            cleaned.append("<email>")
            continue

        if re.fullmatch(r"\d+", original):
            cleaned.append("<number>")
            continue

        word = original.lower()
        word = re.sub(r"[^\w֐-׿]", "", word)

        if not word:
            continue

        cleaned.append(word)

    return cleaned


def extract_words_from_file(file_path: Path):
    words = DocumentTextExtractor().extract_words(Path(file_path))
    return clean_words(words)


def get_document_files(folder_path: Path):
    return [
        p for p in Path(folder_path).iterdir()
        if p.is_file() and p.suffix.lower() in {".pdf", ".txt"}
    ]


def words_to_document(words):
    return " ".join(words)

#hardcoded reciept indicators
RECEIPT_KEYWORDS = [
    "קבלה",
    "receipt",
    "payment confirmation",
    "אישור תשלום",
    "אישור קבלת תשלום",
    "שולם",
    "שולם בתאריך",
    "אישור עסקה",
    "מספר אישור",
    "תעודת תשלום",
    "paid",
    "זיכוי",
    "payment received",
    "transaction approved",
]


class SklearnNaiveBayesClassifier:
    """
    bill/receipt/general classifier, a project specific wrapper for Sklearn naive bayes implementation
    train once then re use saved model weights, saved to pkl file
    """

    def __init__(self):
        self.model = Pipeline([
            (
                "vectorizer",
                CountVectorizer(
                    tokenizer=str.split,
                    token_pattern=None,
                    lowercase=False,
                ),
            ),
            ("classifier", MultinomialNB()),
        ])

        self.is_trained = False

    def train_from_folders(self, folders):
        """Train the model from a folder path containing labeled examples of financial/general docs."""
        texts = []
        labels = []

        for label, folder_path in folders.items():
            folder_path = Path(folder_path)

            for file_path in get_document_files(folder_path):
                try:
                    words = extract_words_from_file(file_path)

                    if not words:
                        continue

                    texts.append(words_to_document(words))
                    labels.append(label)

                except Exception:
                    continue

        if not texts:
            raise ValueError("No training documents found.")

        self.model.fit(texts, labels)
        self.is_trained = True

    def classify_text(self, text: str, subject=None):
        words = clean_words(text.split())
        return self._classify_words(words, subject)

    def classify_file(self, file_path: Path, subject=None):
        words = extract_words_from_file(Path(file_path))
        return self._classify_words(words, subject)

    def decide_bill_or_receipt_from_subject(self, subject: str) -> str:
        """If model decides that doc X is a financial doc
        , then we determine Bill/receipt via keywords in subject."""
        if not subject:
            return "bill"

        normalized_subject = str(subject[::-1]).strip().lower()
        for keyword in RECEIPT_KEYWORDS:
            if keyword[::-1].lower() in normalized_subject:
                return "receipt"

        return "bill"

    def _classify_words(self, words, subject=None):
        if not self.is_trained:
            raise ValueError("Classifier is not trained.")

        # Bayes' rule: invert the trained - P(words | class) into P(class | words).
        text = words_to_document(words)

        prediction = self.model.predict([text])[0]

        probabilities = self.model.predict_proba([text])[0]
        classes = self.model.named_steps["classifier"].classes_

        probs = {
            label: float(prob)
            for label, prob in zip(classes, probabilities)
        }

        # financial/general classifier stage
        if prediction == "financial":
            prediction = self.decide_bill_or_receipt_from_subject(subject)

        return prediction, probs


def save_model(classifier, model_path: Path):
    """Persist an existing trained model after training."""
    model_path.parent.mkdir(parents=True, exist_ok=True)

    with open(model_path, "wb") as f:
        pickle.dump(classifier, f)


def load_or_train_classifier(model_path: Path, folders):
    #if model exists, load it, else train
    if model_path.exists():
        with open(model_path, "rb") as f:
            return pickle.load(f)

    classifier = SklearnNaiveBayesClassifier()
    classifier.train_from_folders(folders)
    save_model(classifier, model_path)
    return classifier


def get_bill_receipt_general_classifier():
    model_path = Path.cwd() / "Bills" / "bill_receipt_general_sklearn_nb.pkl"

    folders = {
        "financial": Path.cwd() / "Bills" / "BillClassification" / "training_data" / "bill_receipt_general" / "financial",
        "general": Path.cwd() / "Bills" / "BillClassification" / "training_data" / "bill_receipt_general" / "general",
    }

    return load_or_train_classifier(model_path, folders)
