import pickle
import re
from pathlib import Path

import pdfplumber
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline


def pdf_words_to_list(pdf_path: Path):
    words = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_words = page.extract_words()
            if not page_words:
                continue

            for word_data in page_words:
                if "text" in word_data:
                    words.append(word_data["text"])

            print("pdf: ", words[:10])

    return words


def txt_words_to_list(txt_path: Path):
    text = txt_path.read_text(encoding="utf-8", errors="replace")
    words = [w[::-1] for w in text.split()]
    print("txt: ", words[:10])
    return words


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
        word = re.sub(r"[^\w\u0590-\u05FF]", "", word)

        if not word:
            continue

        cleaned.append(word)

    return cleaned


def extract_words_from_pdf(pdf_path: Path):
    return clean_words(pdf_words_to_list(pdf_path))


def extract_words_from_txt(txt_path: Path):
    return clean_words(txt_words_to_list(txt_path))


def extract_words_from_file(file_path: Path):
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return extract_words_from_pdf(file_path)

    if suffix == ".txt":
        return extract_words_from_txt(file_path)

    raise ValueError(f"Unsupported file type: {file_path}")


def get_document_files(folder_path: Path):
    return [
        p for p in Path(folder_path).iterdir()
        if p.is_file() and p.suffix.lower() in {".pdf", ".txt"}
    ]


def words_to_document(words):
    return " ".join(words)


class SklearnNaiveBayesClassifier:
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

                except Exception as e:
                    print(f"Could not read {file_path}: {e}")

        if not texts:
            raise ValueError("No training documents found.")

        self.model.fit(texts, labels)
        self.is_trained = True

    def classify_text(self, text: str):
        words = clean_words(text.split())
        return self._classify_words(words)

    def classify_file(self, file_path: Path):
        words = extract_words_from_file(Path(file_path))
        return self._classify_words(words)

    def decide_bill_or_receipt_from_words(self, words):
        RECEIPT_PHRASES = [
            "אישור קבלת תשלום",
            "אישור תשלום",
            "לא לתשלום",
            "שולם בתאריך",
            "אישור עסקה",
            "יתרה לתשלום 0",
            "חוב 0",
            "מספר אישור",
            "תעודת תשלום",
            "קבלה",
            "שולם",
        ]

        for pattern in RECEIPT_PHRASES:
            size = len(pattern)

            for i in range(len(words) - size + 1):
                if words[i:i + size] == pattern:
                    return "receipt"

        return "bill"
    def _classify_words(self, words):
        if not self.is_trained:
            raise ValueError("Classifier is not trained.")

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
            prediction = self.decide_bill_or_receipt_from_words(words)

        return prediction, probs


def save_model(classifier, model_path: Path):
    model_path.parent.mkdir(parents=True, exist_ok=True)

    with open(model_path, "wb") as f:
        pickle.dump(classifier, f)


def load_or_train_classifier(model_path: Path, folders):
    if model_path.exists():
        print("Loading model...")
        with open(model_path, "rb") as f:
            return pickle.load(f)

    print("Training model...")
    classifier = SklearnNaiveBayesClassifier()
    classifier.train_from_folders(folders)
    save_model(classifier, model_path)
    print("Model saved to", model_path)
    return classifier


def get_bill_receipt_general_classifier():
    model_path = Path.cwd() / "Bills" / "bill_receipt_general_sklearn_nb.pkl"

    folders = {
        "financial": Path.cwd() / "Bills" / "BillClassification" / "training_data" / "bill_receipt_general" / "financial",
        "general": Path.cwd() / "Bills" / "BillClassification" / "training_data" / "bill_receipt_general" / "general",
    }

    return load_or_train_classifier(model_path, folders)